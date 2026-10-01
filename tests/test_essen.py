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
<article about="/medien/testbild" class="node node--type-image">
<div class="field field--name-body"><p>Bildbeschreibung außerhalb des Meldungstextes.</p></div>
</article>
<div class="field field--name-field-press-release-author">Polizei Essen</div>
<div class="field field--name-field-base-teaser-text">Am Samstag begann der Einsatz am Nordplatz.</div>
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
    assert record["body"].startswith("Am Samstag begann der Einsatz am Nordplatz.\n")
    assert "Überfall am Nordplatz" in record["body"]
    assert "Falschestraße" not in record["body"]
    assert "Bildbeschreibung" not in record["body"]
    with pytest.raises(ValueError, match="publisher"):
        essen.article_record(ARTICLE.replace(">Polizei Essen</div>", ">Andere Behörde</div>"), url)
    with pytest.raises(ValueError, match="canonical URL"):
        essen.article_record(ARTICLE, "https://essen.polizei.nrw/presse/falscher-fall")


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("Polizei Essen", "Polizei Essen | PLZ: 45141"),
        ("Überfall", "Essen-Nordviertel:\nEin Überfall am Nordplatz."),
        ("Überfall", "45479 MH.-Saarn:\nEin Überfall am Nordplatz."),
        ("Brand", "Oberhausen-Altstadt:\nEin Haus brannte."),
        ("Unfall", "Essen-Kray:\nUnfall auf der A40."),
        ("Zwei Vorfälle", "Essen-Mitte:\nFall eins.\nMülheim:\nFall zwei."),
    ],
)
def test_city_scope_never_performs_programmatic_semantic_filtering(title, body):
    assert essen.city_scope(title, body) == (
        "needs_review", "full-text LLM municipal and scene review required"
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
    assert first["city_scope"] == "needs_review"
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
    assert requested == ["https://essen.polizei.nrw/robots.txt"]


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("target", ["robots", "listing"])
def test_first_source_status_stops_without_retry(tmp_path, monkeypatch, status, target):
    requested = []

    def respond(request):
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(
                status if target == "robots" else 200,
                text="User-agent: *\nDisallow: /admin/\n",
            )
        return httpx.Response(status, text="unavailable")

    client_class = httpx.Client
    monkeypatch.setattr(essen.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        essen.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs),
    )
    with pytest.raises(httpx.HTTPStatusError):
        essen.sync(tmp_path / "stopped.sqlite", 2026, max_pages=1, limit=1)
    assert requested == (
        [essen.ORIGIN + "/robots.txt"]
        if target == "robots" else [essen.ORIGIN + "/robots.txt", essen.archive_url(2026, 0)]
    )


@pytest.mark.parametrize("status", [429, 503, 200])
def test_first_article_error_stops_batch_and_preserves_pending(tmp_path, monkeypatch, status):
    requested = []
    first_url = essen.ORIGIN + "/presse/essen-fall"
    second_url = essen.ORIGIN + "/presse/muelheim-fall"

    def respond(request):
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /admin/\n")
        if request.url.path == "/presse/pressemitteilungen":
            return httpx.Response(200, text=LISTING)
        if request.url.path == "/presse/essen-fall":
            return httpx.Response(
                status,
                text=ARTICLE.replace(">Polizei Essen</div>", ">Andere Behörde</div>")
                if status == 200 else "unavailable",
            )
        if request.url.path == "/presse/muelheim-fall":
            return httpx.Response(200, text=ARTICLE)
        raise AssertionError(request.url)

    client_class = httpx.Client
    monkeypatch.setattr(essen.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        essen.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs),
    )
    path = tmp_path / "articles.sqlite"
    result = essen.sync(path, 2026, max_pages=1, limit=2)
    assert result["failed"] == 1 and result["pending"] == 2
    assert result["stopped_on_source_error"] == {
        "source_url": first_url,
        "http_status": None if status == 200 else status,
        "error_type": "ValueError" if status == 200 else "HTTPStatusError",
    }
    assert requested.count(first_url) == 1
    assert second_url not in requested
    db = essen.connect(path)
    first = db.execute("SELECT body,failures,error FROM reports WHERE source_url=?", (first_url,)).fetchone()
    second = db.execute("SELECT body,error FROM reports WHERE source_url=?", (second_url,)).fetchone()
    assert first["body"] is None and first["failures"] == 1 and first["error"]
    assert second["body"] is None and second["error"] is None
    db.close()
