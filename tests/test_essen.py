import httpx
import pytest

from crimemapsde_cities_11_14 import essen

LISTING = """<div class="view view-list-view-press-releases-solr"><div class="view-content">
<div class="views-row"><H2 class="field-title"><a href="/presse/essen-fall">Essener Fall</a></H2>
<time datetime="2026-09-26T10:10:53+02:00">26. September</time>
<div class="combined-location">Polizei Essen | PLZ: 45141</div></div>
<div class="views-row"><H2 class="field-title"><a href="/presse/muelheim-fall">Mülheimer Fall</a></H2>
<time datetime="2026-09-25T13:49:16+02:00">25. September</time>
<div class="combined-location">Polizei Essen | PLZ: 45479</div></div></div></div>
<nav><a href="?created_1=01.01.2026&amp;page=1" title="Zur nächsten Seite">mehr Ergebnisse anzeigen</a></nav>"""

ARTICLE = r"""<link rel="canonical" href="https://essen.polizei.nrw/presse/essen-fall" />
<article about="/presse/essen-fall" class="node node--type--press-release node--view-mode-full">
<div class="field field--name-field-press-release-author">Polizei Essen</div>
<div class="field field--name-body"><p>Essen-Nordviertel:</p>
<p>Am Samstag ereignete sich ein Überfall am Nordplatz.</p><p>Zeugen werden gesucht.</p></div>
</article><aside>Ein Mülheimer Fest in der Falschestraße.</aside>
<script>var settings={"path":{"currentPath":"node\/217129"}}</script>"""


def test_native_listing_only_accepts_own_ordered_archive_rows():
    rows = essen.listing_rows(LISTING)
    assert len(rows) == 2
    assert rows[0]["published"] == "2026-09-26T10:10:53+02:00"
    assert rows[0]["url"] == "https://essen.polizei.nrw/presse/essen-fall"
    assert essen.next_archive_page(LISTING) == 1
    assert "created_1=01.01.2026" in essen.archive_url(2026, 0)
    with pytest.raises(ValueError, match="origin"):
        essen.listing_rows(LISTING.replace("/presse/essen-fall", "https://example.org/presse/essen-fall"))
    with pytest.raises(ValueError, match="unparsed"):
        essen.listing_rows(LISTING.replace("Polizei Essen | PLZ: 45479", "Andere Behörde"))


def test_article_uses_native_node_id_and_excludes_sidebar():
    url = "https://essen.polizei.nrw/presse/essen-fall"
    record = essen.article_record(ARTICLE, url)
    assert record["source_id"] == "217129"
    assert "Überfall am Nordplatz" in record["body"]
    assert "Falschestraße" not in record["body"]
    with pytest.raises(ValueError, match="publisher"):
        essen.article_record(ARTICLE.replace(">Polizei Essen</div>", ">Andere Behörde</div>"), url)
    with pytest.raises(ValueError, match="canonical URL"):
        essen.article_record(ARTICLE, "https://essen.polizei.nrw/presse/falscher-fall")


def test_city_scope_is_conservative_about_authority_other_cities_and_motorways():
    assert essen.city_scope("Polizei Essen", "Polizei Essen | PLZ: 45141")[0] == "needs_review"
    assert (
        essen.city_scope("Überfall", "Essen-Nordviertel:\nEin Überfall am Nordplatz.")[0] == "essen_candidate"
    )
    assert (
        essen.city_scope("Überfall", "45479 MH.-Saarn:\nEin Überfall am Nordplatz.")[0] == "outside_candidate"
    )
    assert essen.city_scope("Brand", "Oberhausen-Altstadt:\nEin Haus brannte.")[0] == "outside_candidate"
    assert essen.city_scope("Ermittlungen", "Essen-Mitte:\nEine Festnahme in Mülheim.")[0] == "needs_review"
    assert essen.city_scope("Unfall", "Essen-Kray:\nUnfall auf der A40.")[0] == "needs_review"
    assert (
        essen.city_scope("Zwei Vorfälle", "Essen-Mitte:\nFall eins.\nMülheim:\nFall zwei.")[0]
        == "needs_review"
    )


def test_local_checkpoint_preserves_native_id_hash_and_resets_review_on_revision(tmp_path):
    db = essen.connect(tmp_path / "essen.sqlite")
    row = essen.listing_rows(LISTING)[0]
    essen.discover(db, [row], 1)
    record = essen.article_record(ARTICLE, row["url"])
    assert essen.accept(db, row["url"], record, {}, 2) == "new"
    first = db.execute("SELECT source_id,sha256,revision,review_status,city_scope FROM reports").fetchone()
    assert first["source_id"] == "217129"
    assert len(first["sha256"]) == 64
    assert first["revision"] == 1
    assert first["review_status"] == "pending"
    assert first["city_scope"] == "essen_candidate"
    db.execute("UPDATE reports SET review_status='supported'")
    db.commit()
    assert essen.accept(db, row["url"], record, {}, 3) == "unchanged"
    assert db.execute("SELECT review_status FROM reports").fetchone()[0] == "supported"
    essen.discover(db, [{**row, "title": "Essener Fall mit Korrektur"}], 3.5)
    assert db.execute("SELECT review_status FROM reports").fetchone()[0] == "pending"
    db.execute("UPDATE reports SET review_status='supported'")
    db.commit()
    assert (
        essen.accept(db, row["url"], {**record, "body": record["body"] + " Weitere Erkenntnisse."}, {}, 4)
        == "revised"
    )
    updated = db.execute("SELECT sha256,revision,review_status FROM reports").fetchone()
    assert updated["sha256"] != first["sha256"]
    assert updated["revision"] == 2
    assert updated["review_status"] == "pending"
    assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2
    moved_url = "https://essen.polizei.nrw/presse/essen-fall-neu"
    db.execute("UPDATE reports SET review_status='supported'")
    db.commit()
    essen.discover(db, [{**row, "url": moved_url}], 5)
    assert (
        essen.accept(
            db,
            moved_url,
            {**record, "source_url": moved_url, "body": record["body"] + " Weitere Erkenntnisse."},
            {},
            6,
        )
        == "unchanged"
    )
    moved = db.execute("SELECT source_url,source_id,review_status FROM reports").fetchone()
    assert tuple(moved) == (moved_url, "217129", "pending")
    assert db.execute("SELECT count(*) FROM reports").fetchone()[0] == 1
    db.close()


def test_robots_denial_stops_before_archive_request(tmp_path, monkeypatch):
    requested = []

    def respond(request):
        requested.append(str(request.url))
        if len(requested) == 1:
            return httpx.Response(503)
        return httpx.Response(200, text="User-agent: *\nDisallow: /presse/\n")

    client_class = httpx.Client
    monkeypatch.setattr(essen.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        essen.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs),
    )
    with pytest.raises(ValueError, match="robots.txt disallows"):
        essen.sync(tmp_path / "essen.sqlite", 2026, max_pages=1, limit=1)
    assert requested == ["https://essen.polizei.nrw/robots.txt"] * 2
