import json

import pytest

from crimemapsde_cities_11_14 import dresden, nuremberg, nuremberg_newsroom
from crimemapsde_cities_11_14.offline import connect


def _write(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")


DRESDEN = {
    "source_id": "1100218",
    "source_url": "https://medienservice.sachsen.de/medien/news/1100218",
    "publisher": "Polizeidirektion Dresden",
    "title": "Lokal mit Farbe beschmiert",
    "published": "2026-09-27T15:04:00+02:00",
    "body": "Landeshauptstadt Dresden\nOrt: Dresden-Neustadt\nUnbekannte beschmierten ein Lokal an der Louisenstraße.",
}
NUREMBERG = {
    "source_id": "105982",
    "source_url": "https://www.polizei.bayern.de/aktuelles/pressemitteilungen/105982/index.html",
    "publisher": "Polizeipräsidium Mittelfranken",
    "title": "Untersuchungen nach einem Vorfall",
    "published": "2026-07-19",
    "body": "NÜRNBERG. Am Sonntag ereignete sich ein Vorfall in der Innenstadt. Die Polizei sucht Zeugen.",
}


@pytest.mark.parametrize(
    "module,record,scope",
    [
        (dresden, DRESDEN, "dresden_candidate"),
        (nuremberg, NUREMBERG, "nuremberg_candidate"),
    ],
)
def test_local_stage_preserves_official_id_hash_pending_gate_and_revisions(tmp_path, module, record, scope):
    source = tmp_path / "local-source.jsonl"
    db_path = tmp_path / "staged.sqlite"
    _write(source, [record])
    assert module.stage_file(db_path, source, max_records=1)["new"] == 1
    db = connect(db_path)
    saved = db.execute("SELECT * FROM reports").fetchone()
    assert saved["source_id"] == record["source_id"]
    assert saved["source_url"] == record["source_url"]
    assert len(saved["sha256"]) == 64
    assert saved["revision"] == 1
    assert saved["city_scope"] == scope
    assert saved["source_verified"] == 0
    assert saved["review_status"] == "pending"
    db.execute("UPDATE reports SET review_status='supported'")
    db.commit()
    _write(source, [{**record, "body": record["body"] + " Weitere Erkenntnisse."}])
    assert module.stage_file(db_path, source, max_records=1)["revised"] == 1
    saved = db.execute("SELECT revision,review_status,source_verified FROM reports").fetchone()
    assert tuple(saved) == (2, "pending", 0)
    assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2
    db.close()


def test_dresden_bulletin_mixed_city_and_district_stays_uncertain():
    assert (
        dresden.city_scope(
            "Mehrere Meldungen", "Landeshauptstadt Dresden\nOrt: Dresden-Mitte\nLandkreis Meißen\nOrt: Riesa"
        )[0]
        == "needs_review"
    )
    assert (
        dresden.city_scope("Einbruch", "Landkreis Meißen\nOrt: Riesa\nEin Einbruch im Stadtgebiet.")[0]
        == "outside_candidate"
    )
    assert dresden.city_scope("Einbruch", "In Dresden arbeitet die Pressestelle.")[0] == "needs_review"


def test_nuremberg_mixed_municipality_and_motorway_stay_uncertain():
    assert (
        nuremberg.city_scope("Polizei Mittelfranken", "NÜRNBERG. Tat am Platz.\nFÜRTH. Weiterer Vorfall.")[0]
        == "needs_review"
    )
    assert nuremberg.city_scope("Unfall", "NÜRNBERG. Unfall auf der A73.")[0] == "needs_review"
    assert nuremberg.city_scope("Vorfall", "FÜRTH. Ein Vorfall in der Stadt.")[0] == "outside_candidate"


@pytest.mark.parametrize("module,record", [(dresden, DRESDEN), (nuremberg, NUREMBERG)])
def test_offline_adapter_rejects_wrong_origin(tmp_path, module, record):
    source = tmp_path / "local-source.jsonl"
    _write(source, [{**record, "source_url": "https://untrusted.example/medien/news/1100218"}])
    with pytest.raises(ValueError, match="source ID/URL"):
        module.stage_file(tmp_path / "staged.sqlite", source)


def test_dresden_live_crawl_remains_disabled():
    with pytest.raises(RuntimeError, match="live crawl disabled"):
        dresden.live_sync()


def test_offline_stage_is_bounded_and_reports_extra_input(tmp_path):
    source = tmp_path / "local-source.jsonl"
    _write(
        source,
        [
            DRESDEN,
            {
                **DRESDEN,
                "source_id": "1100219",
                "source_url": "https://medienservice.sachsen.de/medien/news/1100219",
            },
        ],
    )
    stats = dresden.stage_file(tmp_path / "staged.sqlite", source, max_records=1)
    assert stats["processed"] == 1
    assert stats["truncated_input"] is True


def test_nuremberg_online_and_offline_databases_cannot_be_mixed(tmp_path):
    source = tmp_path / "local-source.jsonl"
    _write(source, [NUREMBERG])
    offline_db = tmp_path / "police.sqlite"
    assert nuremberg.stage_file(offline_db, source)["new"] == 1
    with pytest.raises(ValueError, match="own SQLite"):
        nuremberg_newsroom.connect(offline_db)
    online_db = tmp_path / "newsroom.sqlite"
    nuremberg_newsroom.connect(online_db).close()
    with pytest.raises(ValueError, match="own SQLite"):
        nuremberg.stage_file(online_db, source)
