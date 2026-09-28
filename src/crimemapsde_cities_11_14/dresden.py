"""Offline staging for Dresden police's official Sachsen Medienservice archive.

The official archive is linked from Polizei Sachsen. Its robots.txt currently
does not return verifiable rules, so this module never crawls that domain.
Locally supplied records remain source-unverified and pending review.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .offline import stage

ARCHIVE = "https://medienservice.sachsen.de/medien/?search%5Binstitution_ids%5D%5B%5D=10997"
PUBLISHER = "Polizeidirektion Dresden"
ARTICLE_PATH = re.compile(r"/medien/news/(\d+)$")
CITY = re.compile(r"(?im)^\s*(?:Landeshauptstadt Dresden|Ort:\s*Dresden(?:-[\wÄÖÜäöüß-]+)?)\s*$")
OUTSIDE = re.compile(
    r"(?im)^\s*(?:Landkreis Meißen|Landkreis Sächsische Schweiz-Osterzgebirge|"
    r"Ort:\s*(?:Meißen|Pirna|Radebeul|Freital|Dippoldiswalde|Riesa|Großenhain)\b[^\n]*)\s*$"
)


def validate_identity(row: dict) -> None:
    url = row.get("source_url")
    ident = row.get("source_id")
    if not isinstance(url, str) or not isinstance(ident, str):
        raise TypeError("Dresden record needs source URL and ID")
    parsed = urlparse(url)
    match = ARTICLE_PATH.fullmatch(parsed.path)
    if (
        (parsed.scheme, parsed.netloc) != ("https", "medienservice.sachsen.de")
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


def live_sync() -> None:
    raise RuntimeError("Dresden live crawl disabled: Medienservice robots.txt has no verified rules")


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
    parser.add_argument("--db", default=".runtime/safety/cities/dresden/police.sqlite")
    parser.add_argument("--max-records", type=int, default=100)
    args = parser.parse_args()
    result = stage_file(args.db, args.input, max_records=args.max_records)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
