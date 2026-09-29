"""Read-only, body-free source audit for the third city group.

This is an intake contract, not a geocoder or publication decision. The local
SQLite body is read only to verify its hash and conservative municipality mark.
No body, excerpt, coordinate or geometry is present in the returned document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from . import dresden, essen, hannover, nuremberg, nuremberg_newsroom
from .registry import CITIES, CitySource

DEFAULT_RUNTIME_ROOT = Path(".runtime/safety/cities")
SCHEMA_VERSION = 1
REPORT_COLUMNS = {
    "essen": {"source_id", "source_url", "title", "published", "body", "sha256", "revision", "city_scope", "scope_evidence", "review_status"},
    "hannover": {"id", "url", "title", "published", "body", "sha256", "revision", "city_scope", "scope_evidence", "review_status"},
    "nuremberg_newsroom": {"id", "url", "title", "published", "body", "sha256", "revision", "city_scope", "scope_evidence", "review_status"},
    "dresden": {"source_id", "source_url", "publisher", "title", "published", "body", "sha256", "revision", "city_scope", "scope_evidence", "source_verified", "review_status"},
    "offline": {"source_id", "source_url", "title", "published", "body", "sha256", "revision", "city_scope", "scope_evidence", "source_verified", "review_status"},
}
REVISION_COLUMNS = {"revision", "sha256"}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def _valid_date(value: object, year: int) -> bool:
    if not isinstance(value, str) or not value.startswith(f"{year:04d}-"):
        return False
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_identity(slug: str, ident: object, url: object, mode: str) -> bool:
    if not isinstance(ident, str) or not ident.isdecimal() or not isinstance(url, str):
        return False
    try:
        if slug == "essen":
            return essen._article_url(url) == url
        if mode in {"hannover", "nuremberg_newsroom"}:
            parsed = urlparse(url)
            article_path = (
                hannover.ARTICLE_PATH if mode == "hannover" else nuremberg_newsroom.ARTICLE_PATH
            )
            match = article_path.fullmatch(parsed.path)
            return (
                (parsed.scheme, parsed.netloc) == ("https", "www.presseportal.de")
                and not parsed.query
                and not parsed.fragment
                and match is not None
                and match[1] == ident
            )
        module = {"dresden": dresden, "nuremberg": nuremberg}[slug]
        module.validate_identity({"source_id": ident, "source_url": url})
    except (TypeError, ValueError):
        return False
    return True


def _row_audit(
    db: sqlite3.Connection, slug: str, city: CitySource, row: sqlite3.Row, year: int, mode: str,
    provenance: sqlite3.Row | None = None,
) -> dict:
    online = mode != "offline"
    newsroom = mode in {"hannover", "nuremberg_newsroom"}
    ident = row["id"] if newsroom else row["source_id"]
    url = row["url"] if newsroom else row["source_url"]
    body = row["body"]
    digest = row["sha256"]
    revision = row["revision"]
    has_body = isinstance(body, str) and len(body.strip()) >= 30
    hash_valid = (
        has_body
        and isinstance(digest, str)
        and len(digest) == 64
        and hashlib.sha256(body.encode()).hexdigest() == digest
    )
    revision_valid = False
    if hash_valid and isinstance(revision, int) and revision > 0 and isinstance(ident, str):
        revision_id = "id" if newsroom else "source_id"
        saved = db.execute(
            f"SELECT sha256 FROM revisions WHERE {revision_id}=? AND revision=?",
            (ident, revision),
        ).fetchone()
        revision_valid = saved is not None and saved["sha256"] == digest
    identity_valid = _valid_identity(slug, ident, url, mode)
    scope_valid = False
    if has_body and isinstance(row["title"], str):
        expected_scope, expected_evidence = {
            "essen": essen.city_scope,
            "dresden": dresden.city_scope,
            "hannover": hannover.city_scope,
            "nuremberg": nuremberg.city_scope,
        }[slug](row["title"], body)
        scope_valid = (
            row["city_scope"] == expected_scope
            and row["scope_evidence"] == expected_evidence
            and bool(expected_evidence.strip())
        )
    locally_verified = identity_valid and hash_valid and revision_valid and _valid_date(row["published"], year)
    # Offline staging has no independently recorded original-source check. A
    # mutable SQLite flag alone cannot establish that verification happened.
    provenance_valid = True
    if mode == "dresden":
        canonical = hashlib.sha256(json.dumps(
            {
                "source_id": row["source_id"], "source_url": row["source_url"],
                "publisher": row["publisher"], "title": row["title"],
                "published": row["published"], "body": body,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        provenance_valid = bool(
            provenance is not None and provenance["publisher"] == dresden.PUBLISHER
            and provenance["institution_id"] == "10997"
            and provenance["record_type"] == "multi_event_bulletin"
            and provenance["source_verified"] == 1
            and provenance["source_sha256"] == canonical
            and isinstance(provenance["raw_html_sha256"], str)
            and len(provenance["raw_html_sha256"]) == 64
            and row["source_verified"] == 1
        )
    source_verified = locally_verified and online and provenance_valid
    evidence_present = isinstance(row["scope_evidence"], str) and bool(row["scope_evidence"].strip())
    candidate = (
        source_verified
        and scope_valid
        and row["city_scope"] == city.candidate_scope
        and row["review_status"] in {"pending", "supported"}
        and _valid_date(row["published"], year)
    )
    return {
        "source_id": ident,
        "source_url": url,
        "source_date": row["published"],
        "sha256": digest,
        "revision": revision,
        "city_scope": row["city_scope"],
        "scope_evidence_present": evidence_present,
        "scope_evidence_valid": scope_valid,
        "review_status": row["review_status"],
        "has_body": has_body,
        "body_hash_valid": hash_valid,
        "revision_hash_valid": revision_valid,
        "source_verified": source_verified,
        "municipal_review_candidate": candidate,
    }


def _base(slug: str, year: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "city": CITIES[slug].export(),
        "year": year,
        "archive_complete": False,
        "source_verified": False,
        "publication_ready": False,
        "blocking_reasons": [],
        "records": [],
        "municipal_review_candidates": [],
    }


def audit_city(
    slug: str,
    year: int,
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    db_path: str | Path | None = None,
) -> dict:
    """Inspect a local source DB without creating or changing it.

    `municipal_review_candidates` are source leads with a defensible city
    marker. They have no scene geometry and do not imply publication approval.
    """
    if slug not in CITIES:
        raise ValueError(f"Unknown third-group city: {slug}")
    if not 2000 <= year <= 2100:
        raise ValueError("Year must be 2000–2100")
    city = CITIES[slug]
    result = _base(slug, year)
    if db_path is not None:
        path = Path(db_path)
    elif slug == "nuremberg":
        newsroom_path = Path(runtime_root) / slug / "newsroom.sqlite"
        staged_path = Path(runtime_root) / slug / "police.sqlite"
        path = newsroom_path if newsroom_path.is_file() or not staged_path.is_file() else staged_path
    else:
        path = Path(runtime_root) / slug / "police.sqlite"
    if not path.is_file():
        result["blocking_reasons"].append("source_db_missing")
    else:
        try:
            with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                report_columns = _columns(db, "reports")
                if slug == "nuremberg":
                    if REPORT_COLUMNS["nuremberg_newsroom"] <= report_columns:
                        mode = "nuremberg_newsroom"
                    elif REPORT_COLUMNS["offline"] <= report_columns:
                        mode = "offline"
                    else:
                        mode = "nuremberg_newsroom"
                elif slug == "dresden":
                    mode = (
                        "dresden"
                        if _columns(db, "sachsen_source_units") and _columns(db, "sachsen_archive_cursor")
                        else "offline"
                    )
                else:
                    mode = "offline" if city.collection_mode == "offline" else slug
                required = REPORT_COLUMNS[mode]
                newsroom = mode in {"hannover", "nuremberg_newsroom"}
                revisions = REVISION_COLUMNS | ({"id"} if newsroom else {"source_id"})
                cursor_table = (
                    "archive_scan" if slug == "essen" else
                    "sachsen_archive_cursor" if slug == "dresden" else "archive_cursor"
                )
                if (
                    not required <= report_columns
                    or not revisions <= _columns(db, "revisions")
                    or (
                        mode != "offline"
                        and not {"year", "complete"} <= _columns(db, cursor_table)
                    )
                ):
                    result["blocking_reasons"].append("source_schema_incompatible")
                else:
                    provenance = {}
                    if mode == "dresden":
                        if not {
                            "source_id", "publisher", "institution_id", "record_type",
                            "source_sha256", "raw_html_sha256", "source_verified",
                        } <= _columns(db, "sachsen_source_units"):
                            result["blocking_reasons"].append("source_schema_incompatible")
                        else:
                            provenance = {
                                row["source_id"]: row
                                for row in db.execute("SELECT * FROM sachsen_source_units")
                            }
                    if mode != "offline":
                        scan = db.execute(
                            f"SELECT complete FROM {cursor_table} WHERE year=?", (year,)
                        ).fetchone()
                        result["archive_complete"] = scan is not None and scan["complete"] == 1
                    rows = db.execute(
                        "SELECT * FROM reports WHERE published LIKE ? ORDER BY published, rowid",
                        (f"{year:04d}-%",),
                    ).fetchall()
                    result["records"] = [
                        _row_audit(
                            db, slug, city, row, year, mode,
                            provenance.get(row["source_id"]) if mode == "dresden" else None,
                        ) for row in rows
                    ]
                    result["municipal_review_candidates"] = [
                        row for row in result["records"] if row["municipal_review_candidate"]
                    ]
                    result["source_verified"] = bool(rows) and all(
                        row["source_verified"] for row in result["records"]
                    )
                    if mode == "offline":
                        result["blocking_reasons"].append("offline_stage_unverified")
        except sqlite3.DatabaseError:
            result["records"] = []
            result["municipal_review_candidates"] = []
            result["archive_complete"] = False
            result["source_verified"] = False
            result["blocking_reasons"].append("source_db_unreadable")
    if city.collection_mode == "offline":
        result["blocking_reasons"].append("live_source_access_blocked")
    if not result["archive_complete"]:
        result["blocking_reasons"].append("archive_completeness_unverified")
    if not result["source_verified"]:
        result["blocking_reasons"].append("source_verification_incomplete")
    result["blocking_reasons"].extend(
        ["revision_bound_codex_review_unrecorded", "owner_batch_approval_unrecorded", "approved_map_build_absent"]
    )
    return result


def audit_group(year: int, *, runtime_root: str | Path = DEFAULT_RUNTIME_ROOT) -> dict:
    """Export the same versioned, body-free contract for all four cities."""
    return {
        "schema_version": SCHEMA_VERSION,
        "group": "cities-11-14",
        "year": year,
        "cities": [audit_city(slug, year, runtime_root=runtime_root) for slug in CITIES],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    args = parser.parse_args()
    print(json.dumps(audit_group(args.year, runtime_root=args.runtime_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
