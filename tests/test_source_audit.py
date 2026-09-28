"""Synthetic contract checks; no network access or real report text."""

import json
import sqlite3

import pytest

from crimemapsde_cities_11_14 import dresden, essen, hannover, nuremberg, nuremberg_newsroom
from crimemapsde_cities_11_14.registry import CITIES
from crimemapsde_cities_11_14.source_audit import audit_city, audit_group

ESSEN_BODY = (
    "Essen-Nordviertel:\n"
    "Ein erfundener Überfall am Testplatz wurde gemeldet. Zeugen werden gesucht."
)
HANNOVER_BODY = (
    "Hannover (ots) Hannover-Mitte. Ein erfundener Vorfall am Testplatz wurde gemeldet."
)
NUREMBERG_BODY = (
    "Nürnberg (ots) In Nürnberg-Ziegelstein wurde ein erfundener Vorfall am Testplatz gemeldet."
)


def _online_record(tmp_path, slug):
    path = tmp_path / f"{slug}.sqlite"
    if slug == "essen":
        db = essen.connect(path)
        listing = {
            "url": "https://essen.polizei.nrw/presse/synthetischer-fall",
            "title": "Synthetischer Fall",
            "published": "2026-09-26T10:10:53+02:00",
        }
        essen.discover(db, [listing], 1)
        essen.accept(
            db,
            listing["url"],
            {"source_id": "217129", "source_url": listing["url"], "body": ESSEN_BODY},
            {},
            2,
        )
    else:
        module = hannover if slug == "hannover" else nuremberg_newsroom
        publisher_id = "66841" if slug == "hannover" else "6013"
        body = HANNOVER_BODY if slug == "hannover" else NUREMBERG_BODY
        db = module.connect(path)
        listing = {
            "id": "6359329",
            "url": f"https://www.presseportal.de/blaulicht/pm/{publisher_id}/6359329",
            "title": "Synthetischer Fall",
            "published": "2026-09-25T15:09:00",
            "district": "",
        }
        module.discover(db, [listing], 1)
        module.accept(db, listing["id"], body, {}, 2)
    db.close()
    return path


def test_registry_is_stable_and_group_audit_does_not_create_databases(tmp_path):
    assert list(CITIES) == ["essen", "dresden", "hannover", "nuremberg"]
    assert [city.epsg for city in CITIES.values()] == [25832, 25833, 25832, 25832]
    assert CITIES["nuremberg"].collection_mode == "online"
    assert CITIES["nuremberg"].source_url.endswith("/blaulicht/nr/6013")
    result = audit_group(2026, runtime_root=tmp_path / "absent")
    assert result["schema_version"] == 1
    assert len(result["cities"]) == 4
    assert not (tmp_path / "absent").exists()
    for city in result["cities"]:
        assert not city["archive_complete"]
        assert not city["source_verified"]
        assert not city["publication_ready"]
        assert city["municipal_review_candidates"] == []
        assert "source_db_missing" in city["blocking_reasons"]


@pytest.mark.parametrize("slug", ["essen", "hannover", "nuremberg"])
def test_online_audit_exports_only_metadata_and_keeps_publication_blocked(tmp_path, slug):
    path = _online_record(tmp_path, slug)
    result = audit_city(slug, 2026, db_path=path)
    assert len(result["records"]) == 1
    expected_scope = {
        "essen": "needs_review",
        "hannover": "hannover_candidate",
        "nuremberg": "nuremberg_candidate",
    }[slug]
    assert len(result["municipal_review_candidates"]) == (0 if slug == "essen" else 1)
    record = result["records"][0]
    assert record["source_id"]
    assert record["source_url"].startswith("https://")
    assert record["source_date"].startswith("2026-")
    assert len(record["sha256"]) == 64
    assert record["revision"] == 1
    assert record["city_scope"] == expected_scope
    assert record["review_status"] == "pending"
    assert record["scope_evidence_valid"]
    assert record["source_verified"]
    assert not result["archive_complete"]
    assert result["source_verified"]
    assert not result["publication_ready"]
    if slug == "nuremberg":
        assert "native_archive_robots_blocked" in result["blocking_reasons"]
        assert "newsroom_coverage_unverified" in result["blocking_reasons"]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "erfundener" not in serialized
    assert "Testplatz" not in serialized
    assert "body" not in record


def test_discovered_without_body_cannot_be_candidate_or_complete_source(tmp_path):
    path = _online_record(tmp_path, "essen")
    db = essen.connect(path)
    essen.discover(
        db,
        [{"url": "https://essen.polizei.nrw/presse/noch-nicht-gelesen", "title": "Noch offen", "published": "2026-09-27T10:00:00+02:00"}],
        3,
    )
    db.execute("INSERT INTO archive_scan VALUES(2026,0,1,4)")
    db.commit()
    db.close()
    result = audit_city("essen", 2026, db_path=path)
    assert result["archive_complete"]
    assert not result["source_verified"]
    assert len(result["records"]) == 2
    assert result["municipal_review_candidates"] == []
    assert not result["records"][1]["municipal_review_candidate"]
    assert "source_verification_incomplete" in result["blocking_reasons"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "0" * 64),
        ("revision", 2),
        ("scope_evidence", ""),
        ("source_url", "https://example.org/presse/fall"),
        ("review_status", "rejected"),
    ],
)
def test_tampered_hash_scope_or_identity_cannot_be_location_candidate(tmp_path, field, value):
    path = _online_record(tmp_path, "essen")
    db = essen.connect(path)
    db.execute(f"UPDATE reports SET {field}=?", (value,))
    db.commit()
    db.close()
    record = audit_city("essen", 2026, db_path=path)["records"][0]
    assert not record["municipal_review_candidate"]


@pytest.mark.parametrize(
    "slug,module,row",
    [
        (
            "dresden",
            dresden,
            {
                "source_id": "1100218",
                "source_url": "https://medienservice.sachsen.de/medien/news/1100218",
                "publisher": "Polizeidirektion Dresden",
                "title": "Synthetische Meldung",
                "published": "2026-09-27T15:04:00+02:00",
                "body": "Landeshauptstadt Dresden\nOrt: Dresden-Neustadt\nEin erfundener Vorfall am Testplatz.",
            },
        ),
        (
            "nuremberg",
            nuremberg,
            {
                "source_id": "105982",
                "source_url": "https://www.polizei.bayern.de/aktuelles/pressemitteilungen/105982/index.html",
                "publisher": "Polizeipräsidium Mittelfranken",
                "title": "Synthetische Meldung",
                "published": "2026-07-19",
                "body": "NÜRNBERG. Ein erfundener Vorfall am Testplatz. Die Polizei sucht Zeugen.",
            },
        ),
    ],
)
def test_offline_records_remain_unverified_even_if_mutable_flag_changes(tmp_path, slug, module, row):
    source = tmp_path / "local.jsonl"
    source.write_text(json.dumps(row, ensure_ascii=False) + "\n")
    path = tmp_path / f"{slug}.sqlite"
    module.stage_file(path, source)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE reports SET source_verified=1")
    result = audit_city(slug, 2026, db_path=path)
    record = result["records"][0]
    assert record["city_scope"] == (
        "needs_review" if slug == "dresden" else "nuremberg_candidate"
    )
    assert record["has_body"] and record["body_hash_valid"]
    assert record["scope_evidence_valid"]
    assert not record["source_verified"]
    assert result["municipal_review_candidates"] == []
    assert not result["archive_complete"]
    assert not result["source_verified"]
    assert not result["publication_ready"]
    assert (
        "offline_stage_unverified"
    ) in result["blocking_reasons"]


def test_nuremberg_completed_newsroom_cursor_does_not_claim_native_archive_complete(tmp_path):
    path = _online_record(tmp_path, "nuremberg")
    db = nuremberg_newsroom.connect(path)
    db.execute("INSERT INTO archive_cursor VALUES(2026,NULL,1,1,3)")
    db.commit()
    db.close()
    result = audit_city("nuremberg", 2026, db_path=path)
    assert len(result["municipal_review_candidates"]) == 1
    assert result["source_verified"]
    assert not result["archive_complete"]
    assert not result["publication_ready"]


def test_nuremberg_default_audit_prefers_newsroom_without_ignoring_legacy_stage(tmp_path):
    root = tmp_path / "cities"
    city_dir = root / "nuremberg"
    city_dir.mkdir(parents=True)
    staged = {
        "source_id": "105982",
        "source_url": "https://www.polizei.bayern.de/aktuelles/pressemitteilungen/105982/index.html",
        "publisher": "Polizeipräsidium Mittelfranken",
        "title": "Synthetische Meldung",
        "published": "2026-07-19",
        "body": "NÜRNBERG. Ein erfundener Vorfall am Testplatz. Die Polizei sucht Zeugen.",
    }
    source = tmp_path / "staged.jsonl"
    source.write_text(json.dumps(staged, ensure_ascii=False) + "\n")
    nuremberg.stage_file(city_dir / "police.sqlite", source)
    offline_result = audit_city("nuremberg", 2026, runtime_root=root)
    assert offline_result["records"][0]["source_id"] == "105982"
    assert not offline_result["source_verified"]

    online_db = nuremberg_newsroom.connect(city_dir / "newsroom.sqlite")
    row = {
        "id": "6359329", "url": "https://www.presseportal.de/blaulicht/pm/6013/6359329",
        "title": "Synthetische Meldung", "published": "2026-09-25T15:09:00", "district": "",
    }
    nuremberg_newsroom.discover(online_db, [row], 1)
    nuremberg_newsroom.accept(online_db, row["id"], NUREMBERG_BODY, {}, 2)
    online_db.close()
    online_result = audit_city("nuremberg", 2026, runtime_root=root)
    assert online_result["records"][0]["source_id"] == "6359329"
    assert online_result["source_verified"]
    assert not online_result["archive_complete"]


def test_unknown_local_schema_fails_closed(tmp_path):
    path = tmp_path / "unrelated.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE reports (id TEXT)")
    result = audit_city("hannover", 2026, db_path=path)
    assert result["records"] == []
    assert result["municipal_review_candidates"] == []
    assert "source_schema_incompatible" in result["blocking_reasons"]
