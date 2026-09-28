"""Offline staging for official Mittelfranken police announcements.

The Bavarian police robots.txt disallows automated article crawling. This
module deliberately has no network collection path. Staged records are
source-unverified leads, never a Nuremberg map or crime inventory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .offline import stage

ARCHIVE = "https://www.polizei.bayern.de/aktuelles/pressemitteilungen/"
PUBLISHER = "Polizeipräsidium Mittelfranken"
ARTICLE_PATH = re.compile(r"/aktuelles/pressemitteilungen/(\d+)/index\.html$")
CITY = re.compile(r"(?im)^\s*(?:NÜRNBERG|Nürnberg(?:-[\wÄÖÜäöüß-]+)?)\s*[.:]")
OUTSIDE = re.compile(r"(?im)^\s*(?:FÜRTH|ERLANGEN|ANSBACH|SCHWABACH|HERZOGENAURACH|ROTH)\s*[.:]")
REGIONAL_ROAD = re.compile(r"\b(?:Autobahn|BAB\s*\d+|A\s*\d{1,3})\b", re.IGNORECASE)


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


def city_scope(_title: str, body: str) -> tuple[str, str]:
    if road := REGIONAL_ROAD.search(body):
        return "needs_review", f"regional road requires scene review: {road[0]}"
    inside = CITY.search(body)
    outside = OUTSIDE.search(body)
    if inside and outside:
        return "needs_review", "mixed Mittelfranken municipality headings"
    if inside:
        return "nuremberg_candidate", inside[0].strip()
    if outside:
        return "outside_candidate", outside[0].strip()
    return "needs_review", "no unambiguous Nürnberg municipal heading"


def live_sync() -> None:
    raise RuntimeError("Nuremberg live crawl disabled by Bavarian police robots.txt")


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
        "--input", required=True, help="local JSONL copied from official source; no network fetch"
    )
    parser.add_argument("--db", default=".runtime/safety/cities/nuremberg/police.sqlite")
    parser.add_argument("--max-records", type=int, default=100)
    args = parser.parse_args()
    result = stage_file(args.db, args.input, max_records=args.max_records)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
