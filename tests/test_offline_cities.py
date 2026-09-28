import hashlib
import json

import httpx
import pytest

from crimemapsde_cities_11_14 import dresden, nuremberg, nuremberg_newsroom
from crimemapsde_cities_11_14.offline import connect, review_rows


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


def _dresden_landing():
    return """<html><body>Polizeidirektion Dresden
    <input value="2026-09-28 17:59:06 UTC" type="hidden"
     name="search[first_searched]" id="search_first_searched" /></body></html>"""


def _dresden_article(source_id="1100218", publisher="Polizeidirektion Dresden"):
    return f"""<html><head><meta name="date" content="2019-01-01" />
    <meta name="author" content="Referat Kommunikation" />
    <meta name="id" content="{source_id}" />
    <meta name="url" content="{dresden.ORIGIN}/medien/news/{source_id}" />
    <meta name="title" content="Mehrere Meldungen" />
    <meta name="date" content="28.09.2026 15:21" />
    <meta name="author" content="{publisher}" /></head><body>
    <h1 id="page-title">Mehrere Meldungen</h1><div class="row content-row">
    <div class="content-col-wide"><div class="row"><h2>Medieninformation Nr. 501|26</h2>
    <div class="col"><h3>Erster Sachverhalt</h3><p>Ort: Dresden<br />Zeit: Sonntag</p>
    <p>Ein vollständiger synthetischer Polizeibericht für die Quellenprüfung.</p></div></div></div>
    <div class="content-col-small">Kontakt und Navigation.</div></div></body></html>"""


def test_dresden_live_public_archive_is_bounded_and_review_gated(tmp_path):
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404, request=request)
        if request.url.path == "/medien/":
            return httpx.Response(200, request=request, text=_dresden_landing())
        if request.url.path == "/medien/news/search.json":
            payload = {
                "teaser": ['<a href="/medien/news/1100218">Meldung 1100218</a>'],
                "disable": True,
                "up_to_date": True,
            }
            return httpx.Response(200, request=request, json=payload)
        if request.url.path == "/medien/news/1100218":
            return httpx.Response(200, request=request, text=_dresden_article())
        raise AssertionError(request.url)

    path = tmp_path / "dresden-live.sqlite"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        stats = dresden.live_sync(
            path, 2026, max_pages=1, limit=2, client=client, sleeper=lambda _seconds: None
        )
    assert requested == ["/robots.txt", "/medien/", "/medien/news/search.json", "/medien/news/1100218"]
    assert stats["robots_status"] == 404 and stats["new"] == 1 and stats["stored"] == 1
    with connect(path) as db:
        row = db.execute("SELECT * FROM reports").fetchone()
        assert row["source_verified"] == 1 and row["city_scope"] == "needs_review"
        assert row["review_status"] == "pending" and row["revision"] == 1
        assert "Kontakt und Navigation" not in row["body"]
        source = db.execute("SELECT * FROM sachsen_source_units").fetchone()
        assert source["institution_id"] == "10997" and source["source_verified"] == 1
    rows = review_rows(
        path, publisher=dresden.PUBLISHER, validate_identity=dresden.validate_identity,
        city_scope=dresden.city_scope,
    )
    assert len(rows) == 1 and rows[0]["source_verified"] is True


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


def test_dresden_saved_html_file_is_bound_to_read_only_review(tmp_path):
    source = tmp_path / "saved.html"
    source.write_text(f"<html><article>{DRESDEN['body']}</article></html>")
    record = {
        **DRESDEN, "source_file": "saved.html",
        "source_file_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    manifest = tmp_path / "source.jsonl"
    _write(manifest, [record])
    db_path = tmp_path / "dresden.sqlite"
    assert dresden.stage_file(db_path, manifest)["new"] == 1
    rows = review_rows(
        db_path, publisher=dresden.PUBLISHER, validate_identity=dresden.validate_identity,
        city_scope=dresden.city_scope,
    )
    assert len(rows) == 1
    assert rows[0]["source_file_sha256"] == record["source_file_sha256"]
    assert rows[0]["source_file_text_matches"] is True
    assert rows[0]["city_scope"] == "dresden_candidate"
    assert rows[0]["source_verified"] is False and rows[0]["publication_ready"] is False
    source.write_text(source.read_text() + "<!-- changed -->")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        review_rows(db_path, publisher=dresden.PUBLISHER,
                    validate_identity=dresden.validate_identity, city_scope=dresden.city_scope)


def test_dresden_pdf_change_resets_review_even_with_same_transcription(tmp_path):
    pdf = tmp_path / "saved.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfirst synthetic fixture\n%%EOF")
    record = {
        **DRESDEN, "source_file": "saved.pdf",
        "source_file_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
    }
    manifest = tmp_path / "source.jsonl"
    _write(manifest, [record])
    db_path = tmp_path / "dresden.sqlite"
    assert dresden.stage_file(db_path, manifest)["new"] == 1
    with connect(db_path) as db:
        db.execute("UPDATE reports SET review_status='supported'")
        db.commit()
    pdf.write_bytes(b"%PDF-1.4\nsecond synthetic fixture\n%%EOF")
    record["source_file_sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    _write(manifest, [record])
    assert dresden.stage_file(db_path, manifest)["revised"] == 1
    rows = review_rows(db_path, publisher=dresden.PUBLISHER,
                       validate_identity=dresden.validate_identity, city_scope=dresden.city_scope)
    assert rows[0]["revision"] == 2
    assert rows[0]["review_status"] == "pending"
    assert rows[0]["source_file_text_matches"] is False
