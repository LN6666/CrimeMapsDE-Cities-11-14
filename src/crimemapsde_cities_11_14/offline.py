"""Local-only staging for official sources without an allowed live crawler.

Records remain unverified leads even when their URL and publisher format pass
validation. A later source-backed review must compare each one to the original.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from datetime import date, datetime
from itertools import islice
from pathlib import Path

from .local_document import verify_local_document

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
 source_id TEXT PRIMARY KEY, source_url TEXT NOT NULL, publisher TEXT NOT NULL,
 title TEXT NOT NULL, published TEXT NOT NULL, publication_precision TEXT NOT NULL,
 body TEXT NOT NULL, sha256 TEXT NOT NULL, revision INTEGER NOT NULL,
 first_seen REAL NOT NULL, observed REAL NOT NULL,
 city_scope TEXT NOT NULL, scope_evidence TEXT NOT NULL,
 source_verified INTEGER NOT NULL DEFAULT 0,
 review_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS revisions (
 source_id TEXT NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL,
 observed REAL NOT NULL, PRIMARY KEY(source_id,revision)
);
CREATE TABLE IF NOT EXISTS runs (
 started REAL PRIMARY KEY, finished REAL, summary TEXT
);
CREATE TABLE IF NOT EXISTS local_evidence (
 source_id TEXT PRIMARY KEY, path TEXT NOT NULL, sha256 TEXT NOT NULL,
 format TEXT NOT NULL, text_matches_file INTEGER NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.execute("PRAGMA journal_mode=WAL")
    return db


def _publication(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise TypeError("publication date must be a string")
    if len(value) == 10:
        return date.fromisoformat(value).isoformat(), "date"
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("publication timestamp needs an explicit UTC offset")
    return stamp.isoformat(), "time"


def stage(
    db_path: str | Path,
    input_path: str | Path,
    *,
    publisher: str,
    validate_identity: Callable[[dict], None],
    city_scope: Callable[[str, str], tuple[str, str]],
    max_records: int = 100,
) -> dict:
    """Checkpoint at most ``max_records`` locally supplied source leads.

    The JSONL is supplied outside Git and never fetched by this function.
    IDs/URLs are validated but the original source has not been independently
    checked; ``source_verified`` stays false and review stays pending.
    """
    if not 1 <= max_records <= 1000:
        raise ValueError("Use 1–1000 local records per staging run")
    if Path(input_path).stat().st_size > 20_000_000:
        raise ValueError("Local JSONL input is too large")
    db = connect(db_path)
    started = time.time()
    stats = {"new": 0, "revised": 0, "unchanged": 0, "processed": 0, "truncated_input": False}
    db.execute("INSERT INTO runs(started) VALUES(?)", (started,))
    db.commit()
    try:
        with Path(input_path).open(encoding="utf-8") as stream:
            for line_number, line in enumerate(islice(stream, max_records + 1), start=1):
                if line_number > max_records:
                    stats["truncated_input"] = True
                    break
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL line {line_number}") from exc
                if not isinstance(row, dict):
                    raise TypeError(f"JSONL line {line_number} must be an object")
                validate_identity(row)
                if row.get("publisher") != publisher:
                    raise ValueError(f"Unexpected publisher on JSONL line {line_number}")
                title = " ".join(str(row.get("title", "")).split())
                body = "\n".join(
                    " ".join(part.split()) for part in str(row.get("body", "")).splitlines() if part.strip()
                )
                if len(title) < 3 or not 30 <= len(body) <= 2_000_000:
                    raise ValueError(f"Missing title or body on JSONL line {line_number}")
                file_evidence = None
                if "source_file" in row or "source_file_sha256" in row:
                    if not row.get("source_file") or not row.get("source_file_sha256"):
                        raise ValueError(f"Local source file and SHA-256 required on line {line_number}")
                    file_evidence = verify_local_document(
                        row["source_file"], row["source_file_sha256"], row["body"],
                        base_dir=Path(input_path).resolve().parent,
                    )
                published, precision = _publication(row.get("published"))
                digest = hashlib.sha256(body.encode()).hexdigest()
                scope, evidence = city_scope(title, body)
                prior_evidence = db.execute(
                    "SELECT sha256 FROM local_evidence WHERE source_id=?", (row["source_id"],)
                ).fetchone()
                prior_file_sha = prior_evidence["sha256"] if prior_evidence else None
                file_sha = file_evidence["sha256"] if file_evidence else None
                old = db.execute("SELECT * FROM reports WHERE source_id=?", (row["source_id"],)).fetchone()
                changed = old is None or old["sha256"] != digest or prior_file_sha != file_sha
                revision = (old["revision"] if old else 0) + int(changed)
                now = time.time()
                if old is None:
                    db.execute(
                        """INSERT INTO reports
                           (source_id,source_url,publisher,title,published,publication_precision,
                            body,sha256,revision,first_seen,observed,city_scope,scope_evidence,
                            source_verified,review_status)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,'pending')""",
                        (
                            row["source_id"],
                            row["source_url"],
                            publisher,
                            title,
                            published,
                            precision,
                            body,
                            digest,
                            revision,
                            now,
                            now,
                            scope,
                            evidence,
                        ),
                    )
                    result = "new"
                else:
                    stale = changed or any(
                        (
                            old["source_url"] != row["source_url"],
                            old["title"] != title,
                            old["published"] != published,
                            old["city_scope"] != scope,
                            old["scope_evidence"] != evidence,
                        )
                    )
                    db.execute(
                        """UPDATE reports SET source_url=?,title=?,published=?,publication_precision=?,
                           body=?,sha256=?,revision=?,observed=?,city_scope=?,scope_evidence=?,
                           source_verified=0,review_status=CASE WHEN ? THEN 'pending' ELSE review_status END
                           WHERE source_id=?""",
                        (
                            row["source_url"],
                            title,
                            published,
                            precision,
                            body,
                            digest,
                            revision,
                            now,
                            scope,
                            evidence,
                            int(stale),
                            row["source_id"],
                        ),
                    )
                    result = "revised" if changed else "unchanged"
                if changed:
                    db.execute(
                        "INSERT INTO revisions VALUES(?,?,?,?)", (row["source_id"], revision, digest, now)
                    )
                db.execute("DELETE FROM local_evidence WHERE source_id=?", (row["source_id"],))
                if file_evidence:
                    db.execute(
                        "INSERT INTO local_evidence VALUES(?,?,?,?,?)",
                        (row["source_id"], file_evidence["path"], file_sha,
                         file_evidence["format"], int(file_evidence["text_matches_file"])),
                    )
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sachsen_source_units'"
                ).fetchone():
                    db.execute(
                        "DELETE FROM sachsen_source_units WHERE source_id=?", (row["source_id"],)
                    )
                db.commit()
                stats[result] += 1
                stats["processed"] += 1
        stats["stored"] = db.execute("SELECT count(*) FROM reports").fetchone()[0]
    except Exception as exc:
        stats["fatal_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        db.execute(
            "UPDATE runs SET finished=?,summary=? WHERE started=?", (time.time(), json.dumps(stats), started)
        )
        db.commit()
        db.close()
    return stats


def review_rows(
    db_path: str | Path, *, publisher: str, validate_identity: Callable[[dict], None],
    city_scope: Callable[[str, str], tuple[str, str]], limit: int = 100, offset: int = 0,
) -> list[dict]:
    """Return local source bodies for LLM review only after read-only integrity checks."""
    if not 1 <= limit <= 200:
        raise ValueError("Review limit must be 1–200")
    if offset < 0:
        raise ValueError("Review offset must be nonnegative")
    path = Path(db_path)
    if not path.is_file():
        raise ValueError("Local source checkpoint is missing")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        has_evidence = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_evidence'"
        ).fetchone() is not None
        has_online = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sachsen_source_units'"
        ).fetchone() is not None
        rows = []
        seen = 0
        for row in db.execute("SELECT * FROM reports ORDER BY published,source_id"):
            online = db.execute(
                "SELECT * FROM sachsen_source_units WHERE source_id=?", (row["source_id"],)
            ).fetchone() if has_online else None
            validate_identity(dict(row))
            if row["publisher"] != publisher:
                raise ValueError("Source publisher mismatch")
            _publication(row["published"])
            body = row["body"]
            if not isinstance(body, str) or hashlib.sha256(body.encode()).hexdigest() != row["sha256"]:
                raise ValueError("Source body hash mismatch")
            revision = db.execute(
                "SELECT sha256 FROM revisions WHERE source_id=? AND revision=?",
                (row["source_id"], row["revision"]),
            ).fetchone()
            if revision is None or revision["sha256"] != row["sha256"]:
                raise ValueError("Source revision hash mismatch")
            if online:
                canonical = hashlib.sha256(json.dumps(
                    {
                        "source_id": row["source_id"], "source_url": row["source_url"],
                        "publisher": row["publisher"], "title": row["title"],
                        "published": row["published"], "body": body,
                    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode()).hexdigest()
                if (online["publisher"] != publisher or online["institution_id"] != "10997"
                        or online["record_type"] != "multi_event_bulletin"
                        or not online["source_verified"] or not row["source_verified"]
                        or online["source_sha256"] != canonical
                        or not isinstance(online["raw_html_sha256"], str)
                        or len(online["raw_html_sha256"]) != 64):
                    raise ValueError("Online source provenance mismatch")
                if row["city_scope"] != "needs_review" or row["review_status"] != "pending":
                    raise ValueError("Online source bypassed the required semantic review gate")
            elif (row["city_scope"], row["scope_evidence"]) != city_scope(row["title"], body):
                raise ValueError("Offline city scope changed")
            file_row = db.execute(
                "SELECT * FROM local_evidence WHERE source_id=?", (row["source_id"],)
            ).fetchone() if has_evidence else None
            if file_row:
                checked = verify_local_document(file_row["path"], file_row["sha256"], body)
                if checked["format"] != file_row["format"] or int(checked["text_matches_file"]) != file_row["text_matches_file"]:
                    raise ValueError("Offline local file metadata mismatch")
            if seen < offset:
                seen += 1
                continue
            rows.append({
                "city": "dresden", "source_id": row["source_id"], "source_url": row["source_url"],
                "published": row["published"], "title": row["title"], "source_body": body,
                "source_sha256": row["sha256"], "revision": row["revision"],
                "source_file_sha256": file_row["sha256"] if file_row else None,
                "source_file_format": file_row["format"] if file_row else None,
                "source_file_text_matches": bool(file_row["text_matches_file"]) if file_row else None,
                "source_file_path": file_row["path"] if file_row else None,
                "city_scope": row["city_scope"], "scope_evidence": row["scope_evidence"],
                "review_status": row["review_status"], "source_verified": bool(online),
                "publication_ready": False,
                "record_type": online["record_type"] if online else "multi_event_bulletin",
                "canonical_source_sha256": online["source_sha256"] if online else None,
                "raw_html_sha256": online["raw_html_sha256"] if online else None,
            })
            if len(rows) >= limit:
                break
        return rows
