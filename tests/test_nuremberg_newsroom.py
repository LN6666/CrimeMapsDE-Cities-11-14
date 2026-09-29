"""Synthetic newsroom checks; no live police or publisher requests."""

import httpx
import pytest

from crimemapsde_cities_11_14 import nuremberg
from crimemapsde_cities_11_14 import nuremberg_newsroom as newsroom

LISTING = """<link rel="next" href="/blaulicht/nr/6013/30">
<article class="news" data-label="6360579"><div class="date">28.09.2026 &ndash; 13:48</div>
<h3 class="news-headline-clamp"><a href="/blaulicht/pm/6013/6360579">
POL-MFR: Vorfall in Nürnberg-Ziegelstein</a></h3></article>"""

ARTICLE = """<nav>Polizeipräsidium Mittelfranken am Testplatz</nav>
<article class="col eight story mbs"><p class="customer"><a>Polizeipräsidium Mittelfranken</a></p>
<h1>POL-MFR: Vorfall in Nürnberg-Ziegelstein</h1>
<p>Nürnberg (ots)</p><p>Im Nürnberger Stadtteil Ziegelstein ereignete sich ein erfundener Vorfall.
Die Polizei sucht Zeugen.</p><ul><li>Hinweis eins zum Ereignis.</li>
<li>Hinweis zwei zum Ereignis.</li></ul><p class="contact-headline">Rückfragen bitte an:</p>
<p class="contact-text">Pressestelle am Testplatz in Nürnberg</p>
<ul><li>Kontaktliste außerhalb des Berichts.</li></ul></article>
<article class="news"><p>Fremder Nachrichtenhinweis</p></article>"""


def test_newsroom_parser_binds_ids_urls_and_next_page_to_publisher():
    rows = newsroom.listing_rows(LISTING)
    assert rows == [{
        "id": "6360579",
        "url": "https://www.presseportal.de/blaulicht/pm/6013/6360579",
        "title": "POL-MFR: Vorfall in Nürnberg-Ziegelstein",
        "published": "2026-09-28T13:48:00+02:00",
        "district": "",
    }]
    assert newsroom.next_url(LISTING) == "https://www.presseportal.de/blaulicht/nr/6013/30"
    with pytest.raises(ValueError, match="unparsed"):
        newsroom.listing_rows(LISTING.replace("/pm/6013/", "/pm/66841/"))
    with pytest.raises(ValueError, match="pagination"):
        newsroom.next_url(LISTING.replace("/nr/6013/30", "/nr/66841/30"))
    with pytest.raises(ValueError, match="pagination"):
        newsroom.next_url(LISTING.replace("/nr/6013/30", "/nr/6013/30?q=1"))


def test_article_parser_keeps_story_lists_but_rejects_wrong_publisher_and_contacts():
    body = newsroom.article_body(ARTICLE)
    assert "Nürnberger Stadtteil Ziegelstein" in body
    assert "Hinweis eins" in body and "Hinweis zwei" in body
    assert "Pressestelle am Testplatz" not in body
    assert "Kontaktliste" not in body
    assert "Fremder Nachrichtenhinweis" not in body
    with pytest.raises(ValueError, match="publisher"):
        newsroom.article_body(ARTICLE.replace(
            "<a>Polizeipräsidium Mittelfranken</a>", "<a>Polizeidirektion Hannover</a>"
        ))


def test_article_parser_preserves_preformatted_evidence_in_order():
    page = ARTICLE.replace(
        '<p class="contact-headline">',
        '<p>Die Beweismittel sind:</p>'
        '<pre>- Ein &amp; zwei <a>Hinweise am Fundort</a>.\n'
        '- Ein Schuhabdruck wurde gesichert.</pre>'
        '<p>Die Ermittlungen dauern an.</p><p class="contact-headline">',
    ).replace(
        '<ul><li>Kontaktliste außerhalb des Berichts.</li></ul>',
        '<pre>Kontaktblock außerhalb des Berichts.</pre>',
    )
    body = newsroom.article_body(page)
    assert (
        'Die Beweismittel sind: - Ein & zwei Hinweise am Fundort . '
        '- Ein Schuhabdruck wurde gesichert. Die Ermittlungen dauern an.'
    ) in body
    assert body.count('Ein Schuhabdruck') == 1
    assert 'Kontaktblock' not in body


def test_collector_never_assigns_semantic_municipality_scope():
    for title, body in (
        ("POL-MFR: Nürnberg", "Nürnberg (ots) Allgemeine Mitteilung."),
        ("Vorfall", "Nürnberg (ots) Im Nürnberger Stadtteil Ziegelstein geschah ein Vorfall."),
        ("Vorfall", "Nürnberg (ots) In Fürth geschah ein Vorfall."),
        ("Vorfall", "In Nürnberg geschah ein Vorfall. Später in Erlangen."),
        ("Vorfall", "Fürth (ots) Die Polizei in Nürnberg ermittelt."),
        ("Vorfall", "Nürnberg (ots) Vorfall im Nürnberger Umland."),
        ("Unfall", "NÜRNBERG. Unfall auf der A73."),
    ):
        assert nuremberg.city_scope(title, body) == (
            "needs_review", nuremberg.LLM_SCOPE_EVIDENCE
        )


def test_report_id_body_hash_revision_and_review_invalidation(tmp_path):
    db = newsroom.connect(tmp_path / "newsroom.sqlite")
    row = newsroom.listing_rows(LISTING)[0]
    newsroom.discover(db, [row], 1)
    body = newsroom.article_body(ARTICLE)
    assert newsroom.accept(db, row["id"], body, {}, 2) == "new"
    saved = db.execute("SELECT * FROM reports").fetchone()
    assert saved["id"] == row["id"] and saved["url"] == row["url"]
    assert len(saved["sha256"]) == 64 and saved["revision"] == 1
    assert saved["city_scope"] == "needs_review"
    assert saved["review_status"] == "pending"
    db.execute("UPDATE reports SET review_status='supported'")
    db.commit()
    assert newsroom.accept(db, row["id"], body, {}, 3) == "unchanged"
    assert db.execute("SELECT review_status FROM reports").fetchone()[0] == "supported"
    newsroom.discover(db, [{**row, "title": "Korrigierter Titel"}], 4)
    assert tuple(db.execute("SELECT checked,review_status FROM reports").fetchone()) == (None, "pending")
    assert newsroom.accept(db, row["id"], body + " Neue Erkenntnisse.", {}, 5) == "revised"
    assert db.execute("SELECT revision FROM reports").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2
    db.execute(
        "UPDATE reports SET city_scope='nuremberg_candidate',scope_evidence='legacy rule',"
        "review_status='supported'"
    )
    db.commit()
    db.close()
    db = newsroom.connect(tmp_path / "newsroom.sqlite")
    migrated = db.execute(
        "SELECT city_scope,scope_evidence,review_status FROM reports"
    ).fetchone()
    assert tuple(migrated) == ("needs_review", nuremberg.LLM_SCOPE_EVIDENCE, "pending")
    db.close()


def test_bounded_newsroom_cursor_resumes_and_never_claims_archive_complete(tmp_path, monkeypatch):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /blaulicht/\n")
        if request.url.path == "/blaulicht/nr/6013":
            return httpx.Response(200, text=LISTING)
        if request.url.path == "/blaulicht/nr/6013/30":
            return httpx.Response(200, text=LISTING.replace("2026", "2025").replace(
                '<link rel="next" href="/blaulicht/nr/6013/30">', ""
            ))
        if request.url.path == "/blaulicht/pm/6013/6360579":
            return httpx.Response(200, text=ARTICLE)
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(newsroom.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        newsroom.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    path = tmp_path / "newsroom.sqlite"
    first = newsroom.sync(path, 2026, pages=1, limit=1)
    assert first["stored"] == 1 and not first["newsroom_scan_complete"]
    second = newsroom.sync(path, 2026, pages=1, limit=1)
    assert second["head_refreshed"] and second["newsroom_scan_complete"]
    assert not second["archive_complete"]
    assert requested.count("/blaulicht/nr/6013/30") == 1
    # A newly published article is intentionally revisited on the next run.
    assert requested.count("/blaulicht/pm/6013/6360579") == 2
    third = newsroom.sync(path, 2026, pages=1, limit=1)
    assert third["newsroom_scan_complete"] and third["head_refreshed"]
    assert requested.count("/blaulicht/nr/6013") == 3
    assert requested.count("/blaulicht/nr/6013/30") == 1
    db = newsroom.connect(path)
    cursor = db.execute(
        "SELECT next_url,pages_scanned,complete FROM archive_cursor WHERE year=2026"
    ).fetchone()
    assert tuple(cursor) == (None, 2, 1)
    db.close()
    with pytest.raises(ValueError, match="bounded"):
        newsroom.sync(path, 2026, pages=11, limit=1)


def test_completed_cursor_recovers_from_old_reset_without_rescanning(tmp_path, monkeypatch):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /blaulicht/\n")
        if request.url.path == "/blaulicht/nr/6013":
            return httpx.Response(200, text=LISTING)
        if request.url.path == "/blaulicht/pm/6013/6360579":
            return httpx.Response(200, text=ARTICLE)
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(newsroom.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        newsroom.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    path = tmp_path / "newsroom.sqlite"
    db = newsroom.connect(path)
    db.execute(
        "INSERT INTO archive_cursor VALUES(?,?,?,?,?)",
        (2026, "https://www.presseportal.de/blaulicht/nr/6013/180", 6, 0, 1),
    )
    db.execute(
        "INSERT INTO runs VALUES(?,?,?)",
        (1, 2, '{"year":2026,"newsroom_scan_complete":true,"cursor_pages_scanned":30}'),
    )
    db.commit()
    db.close()

    result = newsroom.sync(path, 2026, pages=3, limit=1)
    assert result["newsroom_scan_complete"] and result["cursor_pages_scanned"] == 30
    assert requested == ["/robots.txt", "/blaulicht/nr/6013", "/blaulicht/pm/6013/6360579"]
    db = newsroom.connect(path)
    assert tuple(db.execute(
        "SELECT next_url,pages_scanned,complete FROM archive_cursor WHERE year=2026"
    ).fetchone()) == (None, 30, 1)
    db.close()


def test_first_article_429_stops_batch_without_requesting_more(tmp_path, monkeypatch):
    second = LISTING.replace("6360579", "6360578").replace("13:48", "13:47")
    listing = LISTING.replace("</article>", "</article>" + second.split("\n", 1)[1], 1)
    requested = []

    def respond(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /blaulicht/\n")
        if request.url.path == "/blaulicht/nr/6013":
            return httpx.Response(200, text=listing)
        if request.url.path == "/blaulicht/pm/6013/6360579":
            return httpx.Response(429, headers={"Retry-After": "30"})
        if request.url.path == "/blaulicht/pm/6013/6360578":
            raise AssertionError("batch continued after first 429")
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(newsroom.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        newsroom.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    result = newsroom.sync(tmp_path / "newsroom.sqlite", 2026, pages=1, limit=2)
    assert result["failed"] == 1 and result["errors"] == 1 and result["stored"] == 0
    assert requested.count("/blaulicht/pm/6013/6360579") == 1
    assert "/blaulicht/pm/6013/6360578" not in requested


@pytest.mark.parametrize(
    "robots,reason",
    [
        ("<html>User-agent: *</html>", "robots.txt"),
        ("User-agent: AnotherBot\nAllow: /\n", "robots.txt"),
        ("User-agent: *\nDisallow: /blaulicht/\n", "robots.txt disallows"),
    ],
)
def test_robots_fail_closed_before_newsroom(tmp_path, monkeypatch, robots, reason):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        return httpx.Response(200, text=robots)

    real_client = httpx.Client
    monkeypatch.setattr(
        newsroom.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    with pytest.raises(ValueError, match=reason):
        newsroom.sync(tmp_path / "newsroom.sqlite", 2026, pages=1, limit=1)
    assert requested == ["/robots.txt"]


def test_missing_robots_response_fails_before_newsroom(tmp_path, monkeypatch):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        return httpx.Response(404, text="missing")

    real_client = httpx.Client
    monkeypatch.setattr(newsroom.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        newsroom.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    with pytest.raises(httpx.HTTPStatusError):
        newsroom.sync(tmp_path / "newsroom.sqlite", 2026, pages=1, limit=1)
    assert requested == ["/robots.txt"] * 3


def test_first_robots_429_stops_without_retry(tmp_path, monkeypatch):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        return httpx.Response(429, headers={"Retry-After": "30"})

    real_client = httpx.Client
    monkeypatch.setattr(newsroom.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        newsroom.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    with pytest.raises(httpx.HTTPStatusError):
        newsroom.sync(tmp_path / "newsroom.sqlite", 2026, pages=1, limit=1)
    assert requested == ["/robots.txt"]


def test_robots_request_rate_overrides_minimum_delay(tmp_path, monkeypatch):
    sleeps = []

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /blaulicht/\nRequest-rate: 1/4\n")
        if request.url.path == "/blaulicht/nr/6013":
            return httpx.Response(200, text=LISTING)
        if request.url.path == "/blaulicht/pm/6013/6360579":
            return httpx.Response(200, text=ARTICLE)
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(newsroom.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        newsroom.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    result = newsroom.sync(tmp_path / "newsroom.sqlite", 2026, pages=1, limit=1)
    assert result["stored"] == 1
    assert len([seconds for seconds in sleeps if seconds >= 3.9]) >= 2
