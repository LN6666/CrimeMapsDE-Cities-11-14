import httpx
import pytest

from crimemapsde_cities_11_14 import hannover

LISTING = """<link rel="next" href="/blaulicht/nr/66841/30">
<article class="news" data-label="6359329"><div class="date">25.09.2026 &ndash; 15:09</div>
<h3 class="news-headline-clamp"><a href="/blaulicht/pm/66841/6359329">
POL-H: Hannover-Mitte: Radfahrerin stürzt</a></h3></article>"""

ARTICLE = """<nav>Polizeidirektion Hannover an der Falschestraße</nav>
<article class="col eight story mbs"><p class="customer"><a>Polizeidirektion Hannover</a></p>
<h1>POL-H: Hannover-Mitte: Radfahrerin stürzt</h1>
<p>Hannover (ots)</p><p>Hannover-Mitte. Am Donnerstag stürzte eine Radfahrerin in der Joachimstraße.
Zwei Fahrgäste wurden verletzt.</p><p class="contact-headline">Rückfragen bitte an:</p>
<p class="contact-text">Pressestelle an der Falschestraße</p></article>
<article class="news"><p>Andere Nachricht aus Lehrte</p></article>"""


def test_newsroom_parser_keeps_only_publisher_article_ids():
    rows = hannover.listing_rows(LISTING)
    assert rows[0]["id"] == "6359329"
    assert rows[0]["url"] == "https://www.presseportal.de/blaulicht/pm/66841/6359329"
    assert rows[0]["published"] == "2026-09-25T15:09:00"
    assert hannover.next_url(LISTING) == "https://www.presseportal.de/blaulicht/nr/66841/30"
    with pytest.raises(ValueError, match="unparsed"):
        hannover.listing_rows(LISTING.replace("/pm/66841/", "/pm/9999/"))
    with pytest.raises(ValueError, match="pagination"):
        hannover.next_url(LISTING.replace("/nr/66841/30", "/nr/9999/30"))


def test_article_parser_rejects_wrong_publisher_and_excludes_contacts():
    body = hannover.article_body(ARTICLE)
    assert "Joachimstraße" in body
    assert "Falschestraße" not in body
    assert "Lehrte" not in body
    with pytest.raises(ValueError, match="publisher"):
        hannover.article_body(ARTICLE.replace("<a>Polizeidirektion Hannover</a>", "<a>Andere Behörde</a>"))


def test_municipality_scope_does_not_use_newsroom_or_dateline_as_scene():
    assert (
        hannover.city_scope("Polizei Hannover", "Hannover (ots) Allgemeine Informationen.")[0]
        == "needs_review"
    )
    assert (
        hannover.city_scope("Sturz", "Hannover (ots) Hannover-Mitte. Unfall in der Joachimstraße.")[0]
        == "hannover_candidate"
    )
    assert (
        hannover.city_scope("Raub", "Hannover (ots) In Lehrte fand ein Raub statt.")[0] == "outside_candidate"
    )
    assert (
        hannover.city_scope("Raub", "Hannover-Mitte. Tat; später Festnahme in Lehrte.")[0] == "needs_review"
    )
    assert hannover.city_scope("Unfall", "Hannover-Mitte. Unfall auf der A2.")[0] == "needs_review"


def test_checkpoint_hash_and_review_invalidation(tmp_path):
    db = hannover.connect(tmp_path / "h.sqlite")
    row = hannover.listing_rows(LISTING)[0]
    hannover.discover(db, [row], 1)
    body = hannover.article_body(ARTICLE)
    assert hannover.accept(db, row["id"], body, {}, 2) == "new"
    stored = db.execute("SELECT url,sha256,revision,review_status,city_scope FROM reports").fetchone()
    assert stored["url"] == row["url"]
    assert len(stored["sha256"]) == 64
    assert stored["revision"] == 1
    assert stored["review_status"] == "pending"
    assert stored["city_scope"] == "hannover_candidate"
    db.execute("UPDATE reports SET review_status='supported'")
    db.commit()
    assert hannover.accept(db, row["id"], body, {}, 3) == "unchanged"
    assert db.execute("SELECT review_status FROM reports").fetchone()[0] == "supported"
    hannover.discover(db, [{**row, "title": "Korrigierter Titel"}], 4)
    assert db.execute("SELECT review_status FROM reports").fetchone()[0] == "pending"
    assert hannover.accept(db, row["id"], body + " Neue Erkenntnisse.", {}, 5) == "revised"
    assert db.execute("SELECT revision FROM reports").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2
    db.close()


def test_archive_cursor_is_bounded_and_resumes(tmp_path, monkeypatch):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/blaulicht/nr/66841":
            return httpx.Response(200, text=LISTING)
        if request.url.path == "/blaulicht/nr/66841/30":
            return httpx.Response(
                200,
                text=LISTING.replace("25.09.2026", "25.09.2025").replace(
                    '<link rel="next" href="/blaulicht/nr/66841/30">', ""
                ),
            )
        if request.url.path == "/blaulicht/pm/66841/6359329":
            return httpx.Response(200, text=ARTICLE)
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(hannover.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        hannover.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    path = tmp_path / "h.sqlite"
    first = hannover.sync(path, 2026, pages=1, limit=1)
    assert first["stored"] == 1
    assert first["archive_complete"] is False
    second = hannover.sync(path, 2026, pages=1, limit=1)
    assert second["head_refreshed"] is True
    assert second["archive_complete"] is True
    assert requested.count("/blaulicht/nr/66841/30") == 1


def test_missing_robots_rules_fail_closed_before_newsroom(tmp_path, monkeypatch):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        return httpx.Response(200, text="<html>not robots rules</html>")

    real_client = httpx.Client
    monkeypatch.setattr(
        hannover.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    with pytest.raises(ValueError, match="robots.txt"):
        hannover.sync(tmp_path / "h.sqlite", 2026, pages=1, limit=1)
    assert requested == ["/robots.txt"]


def test_robots_disallow_stops_before_newsroom(tmp_path, monkeypatch):
    requested = []

    def respond(request):
        requested.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /blaulicht/\n")

    real_client = httpx.Client
    monkeypatch.setattr(
        hannover.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    with pytest.raises(ValueError, match="robots.txt disallows"):
        hannover.sync(tmp_path / "h.sqlite", 2026, pages=1, limit=1)
    assert requested == ["/robots.txt"]
