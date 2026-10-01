"""Nuremberg source entry point and offline Bavarian-police staging.

Bavarian police pages remain blocked by their robots.txt. The bounded live
path uses only the publisher-identified Presseportal newsroom; older local
staging remains unverified and separate from that newsroom database.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from .offline import stage

ARCHIVE = "https://www.polizei.bayern.de/aktuelles/pressemitteilungen/"
PUBLISHER = "Polizeipräsidium Mittelfranken"
ARTICLE_PATH = re.compile(r"/aktuelles/pressemitteilungen/(\d+)/index\.html$")
LLM_SCOPE_EVIDENCE = "full-text LLM municipality and scene review required"


def validate_identity(row: dict) -> None:
    url = row.get("source_url")
    ident = row.get("source_id")
    if not isinstance(url, str) or not isinstance(ident, str):
        raise TypeError("Nuremberg record needs source URL and ID")
    parsed = urlparse(url)
    match = ARTICLE_PATH.fullmatch(parsed.path)
    if (
        (parsed.scheme, parsed.netloc) != ("https", "www.polizei.bayern.de")
        or not match
        or parsed.query
        or parsed.fragment
        or match[1] != ident
    ):
        raise ValueError("Nuremberg source ID/URL is not an official police article")


def city_scope(_title: str, _body: str) -> tuple[str, str]:
    """Return only the technical gate; the LLM must read and decide every report."""
    return "needs_review", LLM_SCOPE_EVIDENCE


def live_sync(
    db_path: str | Path = ".runtime/safety/cities/nuremberg/newsroom.sqlite",
    year: int | None = None,
    *,
    pages: int = 1,
    limit: int = 5,
    delay: float = 1.0,
) -> dict:
    """Collect only the publisher newsroom; never request Bavarian-police pages."""
    import fcntl

    from .nuremberg_newsroom import sync

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with open(f"{db_path}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return sync(
            db_path,
            datetime.now(UTC).year if year is None else year,
            pages=pages,
            limit=limit,
            delay=delay,
        )


def stage_file(db_path: str | Path, input_path: str | Path, *, max_records: int = 100) -> dict:
    path = Path(db_path)
    if path.is_file():
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(reports)")}
            if columns and not {"source_id", "source_url"} <= columns:
                raise ValueError("Nuremberg offline staging needs its own SQLite database")
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
        "--input", help="offline Bavarian-police JSONL staging; no network fetch"
    )
    parser.add_argument("--db", help="SQLite path; defaults differ for newsroom and offline staging")
    parser.add_argument("--max-records", type=int, default=100)
    parser.add_argument("--year", type=int, default=datetime.now(UTC).year)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if args.input:
        result = stage_file(
            args.db or ".runtime/safety/cities/nuremberg/police.sqlite",
            args.input,
            max_records=args.max_records,
        )
    else:
        result = live_sync(
            args.db or ".runtime/safety/cities/nuremberg/newsroom.sqlite",
            args.year,
            pages=args.pages,
            limit=args.limit,
            delay=args.delay,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.input and (result["failed"] or result["errors"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
