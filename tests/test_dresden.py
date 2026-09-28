import json

import httpx
import pytest

from crimemapsde_cities_11_14 import dresden
from crimemapsde_cities_11_14.offline import connect
from crimemapsde_cities_11_14.sachsen_medienservice import article_page, robots_policy


def landing():
    return """<html><body>Polizeidirektion Dresden
    <input value="2026-09-28 17:59:06 UTC" type="hidden"
     name="search[first_searched]" id="search_first_searched" /></body></html>"""


def article(source_id="1100218", publisher="Polizeidirektion Dresden"):
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


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_robots_only_explicit_404_or_410_are_unavailable(status):
    response = httpx.Response(status, request=httpx.Request("GET", dresden.ORIGIN + "/robots.txt"))
    with pytest.raises(ValueError, match="robots"):
        robots_policy(response, dresden.SPEC)


def test_robots_404_and_410_allow_bounded_access_but_200_disallow_blocks():
    request = httpx.Request("GET", dresden.ORIGIN + "/robots.txt")
    assert robots_policy(httpx.Response(404, request=request), dresden.SPEC).parser is None
    assert robots_policy(httpx.Response(410, request=request), dresden.SPEC).parser is None
    denied = httpx.Response(
        200, request=request, headers={"content-type": "text/plain"},
        text="User-agent: *\nDisallow: /medien/\n",
    )
    with pytest.raises(ValueError, match="disallows"):
        robots_policy(denied, dresden.SPEC)


def test_article_parser_uses_post_id_metadata_and_excludes_sidebar():
    parsed = article_page(
        article(), f"{dresden.ORIGIN}/medien/news/1100218", dresden.SPEC
    )
    assert parsed.source_id == "1100218" and parsed.published.startswith("2026-09-28T15:21")
    assert "Erster Sachverhalt" in parsed.body
    assert "Kontakt und Navigation" not in parsed.body
    with pytest.raises(ValueError, match="publisher mismatch"):
        article_page(
            article(publisher="Andere Behörde"),
            f"{dresden.ORIGIN}/medien/news/1100218",
            dresden.SPEC,
        )


def test_first_article_error_stops_batch_and_persists_checkpoint(tmp_path):
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404, request=request)
        if request.url.path == "/medien/":
            return httpx.Response(200, request=request, text=landing())
        if request.url.path == "/medien/news/search.json":
            payload = {
                "teaser": [
                    '<a href="/medien/news/1100217">erste Meldung</a>',
                    '<a href="/medien/news/1100218">zweite Meldung</a>',
                ],
                "disable": True,
                "up_to_date": True,
            }
            return httpx.Response(200, request=request, content=json.dumps(payload).encode())
        if request.url.path == "/medien/news/1100218":
            return httpx.Response(200, request=request, text=article(publisher="Andere Behörde"))
        raise AssertionError(request.url)

    path = tmp_path / "dresden.sqlite"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        stats = dresden.live_sync(
            path, 2026, max_pages=1, limit=2, client=client, sleeper=lambda _seconds: None
        )
    assert stats["failed"] == 1 and stats["stored"] == 0 and stats["pending"] == 2
    assert "/medien/news/1100217" not in requested
    with connect(path) as db:
        failed = db.execute(
            "SELECT * FROM sachsen_queue WHERE source_id='1100218'"
        ).fetchone()
        assert failed["failures"] == 1 and "publisher mismatch" in failed["error"]
