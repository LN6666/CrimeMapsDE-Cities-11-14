"""Bounded Dresden intake from the official Medienservice Sachsen archive.

The live collector rechecks robots.txt on every run.  An explicit 404/410 is
handled as an unavailable robots file under RFC 9309 section 2.3.1.3; 2xx
rules must parse and allow access, while all other failures stop the run.
Every multi-case bulletin stays pending source-backed scene and city review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .offline import review_rows, stage
from .sachsen_medienservice import (
    ORIGIN,
    ROBOTS_URL,
    Article,
    SourceSpec,
    article_page,
    landing_snapshot,
    robots_policy,
    search_records,
    search_url,
    source_get,
)

ARCHIVE = ORIGIN + "/medien/?search%5Binstitution_ids%5D%5B%5D=10997"
PUBLISHER = "Polizeidirektion Dresden"
USER_AGENT = "CrimeMapsDE-Cities-11-14/0.1 (Dresden official media archive)"
SPEC = SourceSpec("10997", PUBLISHER, ARCHIVE, USER_AGENT)
ARTICLE_PATH = re.compile(r"/medien/news/(\d+)$")
CITY = re.compile(r"(?im)^\s*(?:Landeshauptstadt Dresden|Ort:\s*Dresden(?:-[\wÄÖÜäöüß-]+)?)\s*$")
OUTSIDE = re.compile(
    r"(?im)^\s*(?:Landkreis Meißen|Landkreis Sächsische Schweiz-Osterzgebirge|"
    r"Ort:\s*(?:Meißen|Pirna|Radebeul|Freital|Dippoldiswalde|Riesa|Großenhain)\b[^\n]*)\s*$"
)

ONLINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sachsen_archive_cursor (
 year INTEGER PRIMARY KEY, next_page INTEGER NOT NULL, pages_scanned INTEGER NOT NULL,
 complete INTEGER NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sachsen_queue (
 source_id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE,
 first_seen REAL NOT NULL, last_seen REAL NOT NULL,
 failures INTEGER NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0,
 error TEXT, http_status INTEGER
);
CREATE TABLE IF NOT EXISTS sachsen_source_units (
 source_id TEXT PRIMARY KEY, publisher TEXT NOT NULL, institution_id TEXT NOT NULL,
 record_type TEXT NOT NULL, source_sha256 TEXT NOT NULL, raw_html_sha256 TEXT NOT NULL,
 source_verified INTEGER NOT NULL, observed REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sachsen_source_revisions (
 source_id TEXT NOT NULL, revision INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
 body_sha256 TEXT NOT NULL, observed REAL NOT NULL, PRIMARY KEY(source_id,revision)
);
"""


def validate_identity(row: dict) -> None:
    url = row.get("source_url")
    ident = row.get("source_id")
    if not isinstance(url, str) or not isinstance(ident, str):
        raise TypeError("Dresden record needs source URL and ID")
    parsed = urlparse(url)
    match = ARTICLE_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"medienservice.sachsen.de", "www.medienservice.sachsen.de"}
        or not match
        or parsed.query
        or parsed.fragment
        or match[1] != ident
    ):
        raise ValueError("Dresden source ID/URL is not a native Medienservice article")


def city_scope(_title: str, body: str) -> tuple[str, str]:
    inside = CITY.search(body)
    outside = OUTSIDE.search(body)
    if inside and outside:
        return "needs_review", "mixed city and district bulletin headings"
    if inside:
        return "dresden_candidate", inside[0].strip()
    if outside:
        return "outside_candidate", outside[0].strip()
    return "needs_review", "no unambiguous Dresden municipal heading"


def _ensure_online_schema(db: sqlite3.Connection) -> None:
    db.executescript(ONLINE_SCHEMA)
    existing = {row["name"] for row in db.execute("PRAGMA table_info(reports)")}
    additions = {
        "etag": "TEXT", "modified": "TEXT", "checked": "REAL", "error": "TEXT",
        "failures": "INTEGER NOT NULL DEFAULT 0", "retry_after": "REAL NOT NULL DEFAULT 0",
        "http_status": "INTEGER",
    }
    for name, declaration in additions.items():
        if name not in existing:
            db.execute(f"ALTER TABLE reports ADD COLUMN {name} {declaration}")
    db.commit()


def _canonical_digest(article: Article) -> str:
    payload = json.dumps(
        {
            "source_id": article.source_id,
            "source_url": article.source_url,
            "publisher": PUBLISHER,
            "title": article.title,
            "published": article.published,
            "body": article.body,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _accept_online(
    db: sqlite3.Connection, article: Article, raw_html: bytes, headers, now: float
) -> str:
    body_digest = hashlib.sha256(article.body.encode()).hexdigest()
    source_digest = _canonical_digest(article)
    raw_digest = hashlib.sha256(raw_html).hexdigest()
    old = db.execute("SELECT * FROM reports WHERE source_id=?", (article.source_id,)).fetchone()
    old_source = db.execute(
        "SELECT source_sha256 FROM sachsen_source_units WHERE source_id=?", (article.source_id,)
    ).fetchone()
    changed = old is None or old_source is None or old_source["source_sha256"] != source_digest
    revision = (old["revision"] if old else 0) + int(changed)
    if old is None:
        db.execute(
            """INSERT INTO reports
               (source_id,source_url,publisher,title,published,publication_precision,body,sha256,
                revision,first_seen,observed,city_scope,scope_evidence,source_verified,review_status,
                etag,modified,checked,error,failures,retry_after,http_status)
               VALUES(?,?,?,?,?,'time',?,?,?,?,?,'needs_review',?,1,'pending',?,?,?,NULL,0,0,200)""",
            (
                article.source_id, article.source_url, PUBLISHER, article.title, article.published,
                article.body, body_digest, revision, now, now,
                "source-bound municipal and scene review pending",
                headers.get("etag"), headers.get("last-modified"), now,
            ),
        )
        result = "new"
    else:
        stale = changed or any((
            old["source_url"] != article.source_url, old["publisher"] != PUBLISHER,
            old["title"] != article.title, old["published"] != article.published,
        ))
        db.execute(
            """UPDATE reports SET source_url=?,publisher=?,title=?,published=?,
               publication_precision='time',body=?,sha256=?,revision=?,observed=?,
               city_scope='needs_review',scope_evidence=?,source_verified=1,
               review_status=CASE WHEN ? THEN 'pending' ELSE review_status END,
               etag=?,modified=?,checked=?,error=NULL,failures=0,retry_after=0,http_status=200
               WHERE source_id=?""",
            (
                article.source_url, PUBLISHER, article.title, article.published, article.body,
                body_digest, revision, now, "source-bound municipal and scene review pending",
                int(stale), headers.get("etag"), headers.get("last-modified"), now,
                article.source_id,
            ),
        )
        result = "revised" if changed else "unchanged"
    db.execute(
        """INSERT INTO sachsen_source_units
           (source_id,publisher,institution_id,record_type,source_sha256,raw_html_sha256,
            source_verified,observed) VALUES(?,?,?,'multi_event_bulletin',?,?,1,?)
           ON CONFLICT(source_id) DO UPDATE SET publisher=excluded.publisher,
           institution_id=excluded.institution_id,record_type=excluded.record_type,
           source_sha256=excluded.source_sha256,raw_html_sha256=excluded.raw_html_sha256,
           source_verified=1,observed=excluded.observed""",
        (article.source_id, PUBLISHER, SPEC.institution_id, source_digest, raw_digest, now),
    )
    if changed:
        db.execute(
            "INSERT INTO revisions VALUES(?,?,?,?)",
            (article.source_id, revision, body_digest, now),
        )
        db.execute(
            "INSERT INTO sachsen_source_revisions VALUES(?,?,?,?,?)",
            (article.source_id, revision, source_digest, body_digest, now),
        )
    db.execute("DELETE FROM local_evidence WHERE source_id=?", (article.source_id,))
    db.execute(
        """UPDATE sachsen_queue SET failures=0,retry_after=0,error=NULL,http_status=200
           WHERE source_id=?""",
        (article.source_id,),
    )
    db.commit()
    return result


def _queue_fail(db: sqlite3.Connection, source_id: str, exc: Exception, now: float) -> None:
    row = db.execute(
        "SELECT failures FROM sachsen_queue WHERE source_id=?", (source_id,)
    ).fetchone()
    failures = row["failures"] + 1
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    error = f"{type(exc).__name__}: {exc}"[:300]
    db.execute(
        """UPDATE sachsen_queue SET failures=?,retry_after=?,error=?,http_status=?
           WHERE source_id=?""",
        (failures, now + min(86400, 300 * 2 ** min(failures - 1, 8)), error, status, source_id),
    )
    db.execute(
        """UPDATE reports SET failures=failures+1,retry_after=?,error=?,http_status=?
           WHERE source_id=?""",
        (now + min(86400, 300 * 2 ** min(failures - 1, 8)), error, status, source_id),
    )
    db.commit()


def live_sync(
    db_path: str | Path,
    year: int,
    *,
    max_pages: int = 1,
    limit: int = 2,
    delay: float = 4.0,
    client: httpx.Client | None = None,
    sleeper=time.sleep,
    monotonic=time.monotonic,
) -> dict:
    """Fetch a bounded official date-filtered archive slice and article bodies."""
    if (not 2000 <= year <= datetime.now(UTC).year or not 1 <= max_pages <= 50
            or not 1 <= limit <= 100 or delay < 4):
        raise ValueError("Use an available year, 1-50 pages, 1-100 articles and delay >= 4 seconds")
    from .offline import connect

    db = connect(db_path)
    _ensure_online_schema(db)
    started = time.time()
    stats = {
        "year": year, "archive_pages": 0, "discovered": 0, "new": 0, "revised": 0,
        "unchanged": 0, "failed": 0, "robots_status": None, "archive_complete": False,
        "publication_ready": False,
    }
    db.execute("INSERT INTO runs(started) VALUES(?)", (started,))
    db.commit()
    owned = client is None
    if client is None:
        client = httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": USER_AGENT})
    try:
        with client if owned else nullcontext(client) as session:
            policy = robots_policy(session.get(ROBOTS_URL), SPEC, minimum_delay=delay)
            stats["robots_status"] = policy.status
            last_request = [monotonic()]
            landing = source_get(
                session, ARCHIVE, SPEC, policy, last_request, sleeper=sleeper, monotonic=monotonic
            )
            snapshot = landing_snapshot(landing.text, str(landing.url), SPEC)
            state = db.execute(
                "SELECT next_page,pages_scanned,complete FROM sachsen_archive_cursor WHERE year=?",
                (year,),
            ).fetchone()
            was_complete = bool(state and state["complete"])
            page_number = state["next_page"] if state and not was_complete else 1
            pages_scanned = state["pages_scanned"] if state else 0
            for _ in range(1 if was_complete else max_pages):
                url = search_url(SPEC, first_searched=snapshot, year=year, page=page_number)
                response = source_get(
                    session, url, SPEC, policy, last_request, sleeper=sleeper, monotonic=monotonic
                )
                records, terminal = search_records(response.content, str(response.url), SPEC)
                observed = time.time()
                for source_id, source_url_value in records:
                    db.execute(
                        """INSERT INTO sachsen_queue(source_id,source_url,first_seen,last_seen)
                           VALUES(?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                           source_url=excluded.source_url,last_seen=excluded.last_seen""",
                        (source_id, source_url_value, observed, observed),
                    )
                db.commit()
                stats["archive_pages"] += 1
                stats["discovered"] += len(records)
                pages_scanned += 1
                if not was_complete:
                    db.execute(
                        """INSERT INTO sachsen_archive_cursor(year,next_page,pages_scanned,complete,updated)
                           VALUES(?,?,?,?,?) ON CONFLICT(year) DO UPDATE SET
                           next_page=excluded.next_page,pages_scanned=excluded.pages_scanned,
                           complete=excluded.complete,updated=excluded.updated""",
                        (year, page_number if terminal else page_number + 1, pages_scanned,
                         int(terminal), time.time()),
                    )
                    db.commit()
                if terminal:
                    break
                page_number += 1

            pending = db.execute(
                """SELECT q.*,r.body,r.etag,r.modified,r.checked FROM sachsen_queue q
                   LEFT JOIN reports r ON r.source_id=q.source_id WHERE q.retry_after<=?
                   AND (r.source_id IS NULL OR r.checked IS NULL OR r.checked<?)
                   ORDER BY r.source_id IS NOT NULL,q.source_id DESC LIMIT ?""",
                (started, started - 7 * 86400, limit),
            ).fetchall()
            for row in pending:
                headers = {}
                if row["etag"]:
                    headers["If-None-Match"] = row["etag"]
                if row["modified"]:
                    headers["If-Modified-Since"] = row["modified"]
                try:
                    response = source_get(
                        session, row["source_url"], SPEC, policy, last_request, headers=headers,
                        sleeper=sleeper, monotonic=monotonic,
                    )
                    if response.status_code == 304:
                        if row["body"] is None:
                            raise ValueError("304 without cached Medienservice article")
                        db.execute(
                            """UPDATE reports SET checked=?,error=NULL,failures=0,retry_after=0
                               WHERE source_id=?""",
                            (time.time(), row["source_id"]),
                        )
                        db.execute(
                            """UPDATE sachsen_queue SET error=NULL,failures=0,retry_after=0
                               WHERE source_id=?""",
                            (row["source_id"],),
                        )
                        db.commit()
                        stats["unchanged"] += 1
                        continue
                    article = article_page(response.text, str(response.url), SPEC)
                    if article.source_id != row["source_id"] or article.source_url != row["source_url"]:
                        raise ValueError("Medienservice article identity differs from search result")
                    if not article.published.startswith(f"{year:04d}-"):
                        raise ValueError("Medienservice search returned an article outside the requested year")
                    stats[_accept_online(db, article, response.content, response.headers, time.time())] += 1
                except (httpx.HTTPError, ValueError) as exc:
                    _queue_fail(db, row["source_id"], exc, time.time())
                    stats["failed"] += 1
                    stats["stopped_on_source_error"] = {
                        "source_id": row["source_id"], "source_url": row["source_url"],
                        "error_type": type(exc).__name__,
                    }
                    break
            scan = db.execute(
                "SELECT next_page,pages_scanned,complete FROM sachsen_archive_cursor WHERE year=?",
                (year,),
            ).fetchone()
            stats["next_page"] = scan["next_page"] if scan else 1
            stats["pages_scanned"] = scan["pages_scanned"] if scan else 0
            stats["archive_complete"] = bool(scan and scan["complete"])
            stats["stored"] = db.execute(
                """SELECT count(*) FROM reports r JOIN sachsen_source_units s
                   ON s.source_id=r.source_id WHERE r.published LIKE ? AND s.source_verified=1""",
                (f"{year:04d}-%",),
            ).fetchone()[0]
            stats["pending"] = db.execute(
                """SELECT count(*) FROM sachsen_queue q LEFT JOIN reports r
                   ON r.source_id=q.source_id WHERE r.source_id IS NULL"""
            ).fetchone()[0]
            stats["errors"] = db.execute(
                "SELECT count(*) FROM sachsen_queue WHERE error IS NOT NULL"
            ).fetchone()[0]
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


def stage_file(db_path: str | Path, input_path: str | Path, *, max_records: int = 100) -> dict:
    return stage(
        db_path,
        input_path,
        publisher=PUBLISHER,
        validate_identity=validate_identity,
        city_scope=city_scope,
        max_records=max_records,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", help="local JSONL copied from official source; no network fetch"
    )
    parser.add_argument("--export-review", help="local NDJSON for source-first review")
    parser.add_argument("--db", default=".runtime/safety/cities/dresden/police.sqlite")
    parser.add_argument("--live", action="store_true", help="bounded public Medienservice intake")
    parser.add_argument("--year", type=int, default=datetime.now(UTC).year)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--delay", type=float, default=4.0)
    parser.add_argument("--max-records", type=int, default=100)
    parser.add_argument("--review-offset", type=int, default=0)
    args = parser.parse_args()
    if not args.input and not args.export_review and not args.live:
        parser.error("Provide --live, --input or --export-review")
    if args.input and args.live:
        parser.error("Run live and local-file intake separately")
    result = None
    if args.input or args.live:
        import fcntl

        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        with open(args.db + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = (
                stage_file(args.db, args.input, max_records=args.max_records)
                if args.input else
                live_sync(
                    args.db, args.year, max_pages=args.max_pages,
                    limit=args.max_records, delay=args.delay,
                )
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.export_review:
        output = Path(args.export_review)
        if (output.suffix != ".ndjson" or output.resolve() == Path(args.db).resolve()
                or (args.input and output.resolve() == Path(args.input).resolve())):
            parser.error("Review output must be a distinct .ndjson file")
        if not output.resolve().is_relative_to(Path.cwd().resolve() / ".runtime"):
            parser.error("Review output must be under .runtime/")
        rows = review_rows(
            args.db, publisher=PUBLISHER, validate_identity=validate_identity,
            city_scope=city_scope, limit=args.max_records, offset=args.review_offset,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        print(json.dumps({"review_rows": len(rows), "output": str(output)}))
    if result and (result.get("failed") or result.get("errors")):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
