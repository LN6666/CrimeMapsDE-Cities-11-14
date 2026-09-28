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
CITY = re.compile(r"(?im)^\s*(?:NÜRNBERG|Nürnberg(?:-[\wÄÖÜäöüß-]+)?)\s*[.:]")
OUTSIDE = re.compile(r"(?im)^\s*(?:FÜRTH|ERLANGEN|ANSBACH|SCHWABACH|HERZOGENAURACH|ROTH)\s*[.:]")
INSIDE_SCENE = re.compile(
    r"\b(?:in Nürnberg(?:-[\wÄÖÜäöüß-]+)?|"
    r"im Nürnberger (?:Stadtteil(?:\s+[\wÄÖÜäöüß-]+)?|Stadtgebiet|Norden|Süden|Osten|Westen|Zentrum)|"
    r"in der Nürnberger Innenstadt|Nürnberg-[\wÄÖÜäöüß-]+)\b",
    re.IGNORECASE,
)
OUTSIDE_SCENE = re.compile(
    r"\b(?:Fürth|Fürther|Erlangen|Erlanger|Ansbach|Ansbacher|Schwabach|Schwabacher|"
    r"Herzogenaurach|Roth|Lauf an der Pegnitz|Feucht|Stein|Zirndorf|Schwaig|"
    r"Bad Windsheim|Neustadt an der Aisch)\b",
    re.IGNORECASE,
)
REGIONAL_ROAD = re.compile(
    r"\b(?:Autobahn|BAB\s*\d+|A\s*\d{1,3}|Bundesstraße|B\s*\d{1,3})\b",
    re.IGNORECASE,
)
DATELINE = re.compile(r"^\s*(?P<place>[^.!?]{1,80}?)\s*\(ots\)\s*[-–]?\s*", re.IGNORECASE)


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


def city_scope(title: str, body: str) -> tuple[str, str]:
    """Return only a conservative municipal-review lead, never an offence point."""
    dateline = DATELINE.match(body)
    narrative = body[dateline.end():] if dateline else body
    if road := REGIONAL_ROAD.search(title + " " + narrative):
        return "needs_review", f"regional road requires scene review: {road[0]}"
    inside = CITY.search(narrative) or INSIDE_SCENE.search(narrative)
    outside = OUTSIDE.search(narrative) or OUTSIDE_SCENE.search(narrative)
    if dateline and not re.fullmatch(
        r"Nürnberg(?:-[\wÄÖÜäöüß-]+)?", dateline["place"].strip(), re.IGNORECASE
    ) and inside:
        return "needs_review", f"non-Nürnberg dateline plus municipal mention: {dateline['place'].strip()}"
    if inside and outside:
        return "needs_review", f"mixed municipality mentions: {inside[0].strip()}; {outside[0].strip()}"
    if inside:
        return "nuremberg_candidate", inside[0].strip()
    if outside:
        return "outside_candidate", outside[0].strip()
    return "needs_review", "no explicit Nürnberg scene evidence"


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
