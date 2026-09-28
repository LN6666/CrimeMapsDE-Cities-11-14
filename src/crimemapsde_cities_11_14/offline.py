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
                if len(title) < 3 or len(body) < 30:
                    raise ValueError(f"Missing title or body on JSONL line {line_number}")
                published, precision = _publication(row.get("published"))
                digest = hashlib.sha256(body.encode()).hexdigest()
                scope, evidence = city_scope(title, body)
                old = db.execute("SELECT * FROM reports WHERE source_id=?", (row["source_id"],)).fetchone()
                changed = old is None or old["sha256"] != digest
                revision = (old["revision"] if old else 0) + int(changed)
                now = time.time()
                if old is None:
                    db.execute(
                        """INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,'pending')""",
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
