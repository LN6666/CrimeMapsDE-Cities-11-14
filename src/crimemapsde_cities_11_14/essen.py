"""Bounded, checkpointed intake from the native Polizei Essen press archive.

The press office also publishes events in Mülheim, Oberhausen and on regional
motorways. Municipal scope is a review lead only. This module stores source
text locally; it neither geocodes nor publishes a city map.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

ORIGIN = "https://essen.polizei.nrw"
ARCHIVE = ORIGIN + "/presse/pressemitteilungen"
USER_AGENT = "CrimeMapsDE-Cities-11-14/0.1 (native Polizei Essen press archive)"
ARTICLE_PATH = re.compile(r"/presse/[a-z0-9][a-z0-9-]*$")
NODE_ID = re.compile(r'"currentPath":"node\\?/+(\d+)"')
CANONICAL = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"')
NEXT_PAGE = re.compile(r'href="\?[^"]*?\bpage=(\d+)"[^>]*title="Zur nächsten Seite"')
ARTICLE = re.compile(
    r'<article\s+about="([^"]+)"[^>]*node--type--press-release[^>]*>.*?</article>', re.DOTALL
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
 source_url TEXT PRIMARY KEY,
 source_id TEXT UNIQUE,
 title TEXT NOT NULL,
 published TEXT NOT NULL,
 body TEXT,
 sha256 TEXT,
 etag TEXT,
 modified TEXT,
 checked REAL,
 retry_after REAL NOT NULL DEFAULT 0,
 failures INTEGER NOT NULL DEFAULT 0,
 error TEXT,
 first_seen REAL NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0,
 city_scope TEXT NOT NULL DEFAULT 'needs_review',
 scope_evidence TEXT NOT NULL DEFAULT '',
 review_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS revisions (
 source_id TEXT NOT NULL, revision INTEGER NOT NULL,
 sha256 TEXT NOT NULL, observed REAL NOT NULL,
 PRIMARY KEY(source_id, revision)
);
CREATE TABLE IF NOT EXISTS archive_scan (
 year INTEGER PRIMARY KEY, next_page INTEGER NOT NULL,
 complete INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 started REAL PRIMARY KEY, finished REAL, summary TEXT
);
"""


def _text(value: str) -> str:
    return " ".join(html.unescape(value).split())


def _article_url(value: str) -> str:
    parsed = urlparse(urljoin(ORIGIN, html.unescape(value)))
    if (parsed.scheme, parsed.netloc) != ("https", "essen.polizei.nrw"):
        raise ValueError("Article URL escaped the Polizei Essen origin")
    if not ARTICLE_PATH.fullmatch(parsed.path) or parsed.query or parsed.fragment:
        raise ValueError("Unexpected native press article path")
    return parsed.geturl()


class ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.view_depth = None
        self.row_depth = None
        self.field = None
        self.rows_seen = 0
        self.rows: list[dict] = []
        self.current: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "div":
            self.depth += 1
            if "view-list-view-press-releases-solr" in classes:
                self.view_depth = self.depth
            elif self.view_depth is not None and self.row_depth is None and "views-row" in classes:
                self.row_depth = self.depth
                self.rows_seen += 1
                self.current = {"url": "", "title": "", "published": "", "authority": ""}
            elif self.current is not None and "combined-location" in classes:
                self.field = "authority"
        if self.current is None:
            return
        if tag == "h2" and "field-title" in classes:
            self.field = "title"
        elif tag == "a" and self.field == "title":
            self.current["url"] = _article_url(attrs.get("href") or "")
        elif tag == "time":
            self.current["published"] = attrs.get("datetime") or ""

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.field:
            self.current[self.field] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self.field == "title":
            self.field = None
        if tag != "div":
            return
        if self.current is not None and self.field == "authority":
            self.field = None
        if self.row_depth == self.depth:
            row = self.current
            if row is not None:
                row["title"] = _text(row["title"])
                row["authority"] = _text(row["authority"])
                authority = row["authority"].split("|", 1)[0].strip()
                if row["url"] and row["title"] and row["published"] and authority == "Polizei Essen":
                    if datetime.fromisoformat(row["published"]).tzinfo is None:
                        raise ValueError("Native Essen archive timestamp has no offset")
                    self.rows.append(row)
            self.current = None
            self.row_depth = None
        if self.view_depth == self.depth:
            self.view_depth = None
        self.depth -= 1


def listing_rows(page: str) -> list[dict]:
    parser = ListingParser()
    parser.feed(page)
    if not parser.rows_seen or parser.rows_seen != len(parser.rows):
        raise ValueError("Native Essen archive contains no, foreign or unparsed rows")
    dates = [row["published"] for row in parser.rows]
    if dates != sorted(dates, reverse=True):
        raise ValueError("Native Essen archive order changed")
    return parser.rows


def next_archive_page(page: str) -> int | None:
    match = NEXT_PAGE.search(page)
    return int(match[1]) if match else None


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.body_depth = None
        self.author_depth = None
        self.author: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        self.depth += 1
        classes = (dict(attrs).get("class") or "").split()
        if "field--name-body" in classes:
            self.body_depth = self.depth
        elif "field--name-field-press-release-author" in classes:
            self.author_depth = self.depth

    def handle_data(self, data: str) -> None:
        if self.body_depth is not None:
            self.parts.append(data)
        if self.author_depth is not None:
            self.author.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.body_depth is not None and tag in {"p", "li", "br"}:
            self.parts.append("\n")
        if tag == "div":
            if self.depth == self.body_depth:
                self.body_depth = None
            if self.depth == self.author_depth:
                self.author_depth = None
            self.depth -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.body_depth is not None and tag == "br":
            self.parts.append("\n")


def article_record(page: str, requested_url: str) -> dict:
    node = NODE_ID.search(page)
    canonical = CANONICAL.search(page)
    if not node or not canonical:
        raise ValueError("Native Essen article ID or canonical URL missing")
    url = _article_url(canonical[1])
    if url != requested_url:
        raise ValueError("Native Essen canonical URL differs from fetched URL")
    article = ARTICLE.search(page)
    if not article or article[1] != urlparse(url).path:
        raise ValueError("Native Essen press-release article container missing")
    parser = ArticleParser()
    parser.feed(article[0])
    body = "\n".join(_text(part) for part in "".join(parser.parts).splitlines() if _text(part))
    if _text("".join(parser.author)) != "Polizei Essen" or len(body) < 30:
        raise ValueError("Native Essen publisher or body check failed")
    return {"source_id": node[1], "source_url": url, "body": body}


LEAD = re.compile(
    r"^\s*(?:\d{5}\s+)?(?P<city>Essen|E\.|Mülheim\s+an\s+der\s+Ruhr|Mülheim|MH\.|Oberhausen|OB\.)"
    r"(?:[-.\s][^:\n]{0,55})?:",
    re.IGNORECASE | re.MULTILINE,
)
OUTSIDE = re.compile(
    r"\b(?:Mülheim(?:\s+an\s+der\s+Ruhr)?|Oberhausen|Duisburg|Bottrop|Gelsenkirchen)\b", re.IGNORECASE
)
INSIDE = re.compile(r"\bEssen(?:-[\wÄÖÜäöüß]+)?\b", re.IGNORECASE)
MOTORWAY = re.compile(r"\b(?:Autobahn|Bundesautobahn|BAB\s*\d+|A\s*\d{1,3})\b", re.IGNORECASE)


def city_scope(title: str, body: str) -> tuple[str, str]:
    """Flag likely municipality for review; never infer an incident coordinate."""
    narrative = re.sub(
        r"\b(?:Polizei|Polizeipräsidium|Staatsanwaltschaft)\s+Essen\b", "", title + "\n" + body
    )
    if motorway := MOTORWAY.search(narrative):
        return "needs_review", f"motorway requires scene review: {motorway[0]}"
    leads = list(LEAD.finditer(body))
    if len(leads) != 1:
        return "needs_review", "no single explicit municipal scene heading"
    lead = leads[0]["city"]
    if lead.lower() in {"essen", "e."}:
        if outside := OUTSIDE.search(narrative):
            return "needs_review", f"Essen lead and other municipality: {outside[0]}"
        return "essen_candidate", leads[0][0]
    if INSIDE.search(narrative):
        return "needs_review", f"outside-city lead and Essen mention: {lead}"
    return "outside_candidate", leads[0][0]


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.execute("PRAGMA journal_mode=WAL")
    return db


def discover(db: sqlite3.Connection, rows: list[dict], now: float) -> None:
    for row in rows:
        db.execute(
            """INSERT INTO reports(source_url,title,published,first_seen)
               VALUES(?,?,?,?) ON CONFLICT(source_url) DO UPDATE SET
               title=excluded.title,published=excluded.published,
               review_status=CASE WHEN reports.title<>excluded.title OR
               reports.published<>excluded.published THEN 'pending' ELSE reports.review_status END""",
            (row["url"], row["title"], row["published"], now),
        )
    db.commit()


def accept(db: sqlite3.Connection, url: str, record: dict, headers: dict, now: float) -> str:
    canonical_url = record["source_url"]
    existing = db.execute("SELECT * FROM reports WHERE source_id=?", (record["source_id"],)).fetchone()
    alias_changed = canonical_url != url or (existing is not None and existing["source_url"] != canonical_url)
    if existing is not None and existing["source_url"] != canonical_url:
        db.execute("DELETE FROM reports WHERE source_url=? AND source_id IS NULL", (canonical_url,))
        db.execute("UPDATE reports SET source_url=? WHERE source_id=?", (canonical_url, record["source_id"]))
    elif canonical_url != url:
        db.execute("UPDATE reports SET source_url=? WHERE source_url=?", (canonical_url, url))
    row = db.execute("SELECT * FROM reports WHERE source_url=?", (canonical_url,)).fetchone()
    if row is None:
        raise ValueError("Article not discovered in native archive")
    body = record["body"]
    digest = hashlib.sha256(body.encode()).hexdigest()
    changed = row["sha256"] != digest
    revision = row["revision"] + int(changed)
    scope, evidence = city_scope(row["title"], body)
    db.execute(
        """UPDATE reports SET source_id=?,body=?,sha256=?,etag=?,modified=?,checked=?,
           error=NULL,retry_after=0,failures=0,revision=?,city_scope=?,scope_evidence=?,
           review_status=CASE WHEN ? THEN 'pending' ELSE review_status END
           WHERE source_url=?""",
        (
            record["source_id"],
            body,
            digest,
            headers.get("etag"),
            headers.get("last-modified"),
            now,
            revision,
            scope,
            evidence,
            int(changed or alias_changed or row["city_scope"] != scope or row["scope_evidence"] != evidence),
            canonical_url,
        ),
    )
    if changed:
        db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (record["source_id"], revision, digest, now))
    db.commit()
    return "new" if row["sha256"] is None else "revised" if changed else "unchanged"


def fail(db: sqlite3.Connection, url: str, error: str, now: float) -> None:
    row = db.execute("SELECT failures FROM reports WHERE source_url=?", (url,)).fetchone()
    failures = row[0] + 1
    retry_after = now + min(86400, 300 * 2 ** min(failures - 1, 8))
    db.execute(
        "UPDATE reports SET failures=?,error=?,retry_after=? WHERE source_url=?",
        (failures, error[:200], retry_after, url),
    )
    db.commit()


def archive_url(year: int, page: int) -> str:
    query = {"created_1": f"01.01.{year}", "created_2": f"31.12.{year}"}
    if page:
        query["page"] = str(page)
    return ARCHIVE + "?" + urlencode(query)


def sync(
    path: str | Path,
    year: int,
    *,
    full: bool = False,
    max_pages: int = 2,
    limit: int = 20,
    delay: float = 1.0,
) -> dict:
    """Scan a bounded native archive slice and a bounded number of article bodies."""
    if (
        not 2015 <= year <= datetime.now(UTC).year
        or not 1 <= max_pages <= 100
        or not 1 <= limit <= 500
        or delay < 1
    ):
        raise ValueError("Use an available year, 1–100 pages, 1–500 articles and delay >= 1 second")
    db = connect(path)
    started = time.time()
    stats = {
        "year": year,
        "full_archive_scan": full,
        "archive_pages": 0,
        "discovered": 0,
        "new": 0,
        "revised": 0,
        "unchanged": 0,
        "failed": 0,
    }
    db.execute("INSERT INTO runs(started) VALUES(?)", (started,))
    db.commit()
    try:
        with httpx.Client(timeout=25, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            robots_response = client.get(ORIGIN + "/robots.txt")
            robots_response.raise_for_status()
            if (
                str(robots_response.url) != ORIGIN + "/robots.txt"
                or "user-agent:" not in robots_response.text.lower()
            ):
                raise ValueError("Native Essen robots.txt could not be verified")
            robots = RobotFileParser()
            robots.parse(robots_response.text.splitlines())
            delay = max(delay, float(robots.crawl_delay(USER_AGENT) or 0))
            last_request = time.monotonic()

            def get(url: str, headers: dict | None = None) -> httpx.Response:
                nonlocal last_request
                for _ in range(4):
                    parsed = urlparse(url)
                    if (parsed.scheme, parsed.netloc) != ("https", "essen.polizei.nrw"):
                        raise ValueError("Unexpected native Essen origin")
                    if not robots.can_fetch(USER_AGENT, url):
                        raise ValueError("robots.txt disallows " + url)
                    time.sleep(max(0, delay - (time.monotonic() - last_request)))
                    last_request = time.monotonic()
                    response = client.get(url, headers=headers)
                    if response.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(str(response.url), response.headers["location"])
                        continue
                    if response.status_code != 304:
                        response.raise_for_status()
                    return response
                raise ValueError("Too many native Essen redirects")

            state = db.execute("SELECT next_page,complete FROM archive_scan WHERE year=?", (year,)).fetchone()
            page_number = state["next_page"] if full and state and not state["complete"] else 0
            for _ in range(max_pages if full else min(max_pages, 2)):
                page = get(archive_url(year, page_number)).text
                rows = listing_rows(page)
                if any(not row["published"].startswith(str(year)) for row in rows):
                    raise ValueError("Native Essen archive ignored year filter")
                discover(db, rows, time.time())
                stats["archive_pages"] += 1
                stats["discovered"] += len(rows)
                following = next_archive_page(page)
                if following is not None and following != page_number + 1:
                    raise ValueError("Native Essen archive pagination gap or loop")
                complete = following is None
                if full:
                    db.execute(
                        """INSERT INTO archive_scan(year,next_page,complete,updated) VALUES(?,?,?,?)
                           ON CONFLICT(year) DO UPDATE SET next_page=excluded.next_page,
                           complete=excluded.complete,updated=excluded.updated""",
                        (year, 0 if complete else following, int(complete), time.time()),
                    )
                    db.commit()
                if complete:
                    break
                page_number = following

            pending = db.execute(
                """SELECT * FROM reports WHERE published LIKE ? AND retry_after<=? AND
                   (body IS NULL OR checked IS NULL OR checked<? OR published>=?)
                   ORDER BY body IS NOT NULL,COALESCE(checked,0),published DESC LIMIT ?""",
                (
                    f"{year}-%",
                    started,
                    started - 7 * 86400,
                    datetime.fromtimestamp(started - 2 * 86400, UTC).isoformat()[:19],
                    limit,
                ),
            ).fetchall()
            for row in pending:
                headers = {}
                if row["etag"]:
                    headers["If-None-Match"] = row["etag"]
                if row["modified"]:
                    headers["If-Modified-Since"] = row["modified"]
                try:
                    response = get(row["source_url"], headers)
                    if response.status_code == 304:
                        if row["body"] is None:
                            raise ValueError("304 without cached native article")
                        db.execute(
                            "UPDATE reports SET checked=?,error=NULL,failures=0,retry_after=0 WHERE source_url=?",
                            (time.time(), row["source_url"]),
                        )
                        db.commit()
                        stats["unchanged"] += 1
                    else:
                        record = article_record(response.text, str(response.url))
                        stats[accept(db, row["source_url"], record, response.headers, time.time())] += 1
                except (httpx.HTTPError, ValueError) as exc:
                    fail(db, row["source_url"], f"{type(exc).__name__}: {exc}", time.time())
                    stats["failed"] += 1
                    stats["stopped_on_source_error"] = {
                        "source_url": row["source_url"],
                        "http_status": exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None,
                        "error_type": type(exc).__name__,
                    }
                    break
            stats["stored"] = db.execute(
                "SELECT count(*) FROM reports WHERE published LIKE ? AND body IS NOT NULL", (f"{year}-%",)
            ).fetchone()[0]
            stats["pending"] = db.execute(
                "SELECT count(*) FROM reports WHERE published LIKE ? AND body IS NULL", (f"{year}-%",)
            ).fetchone()[0]
            stats["errors"] = db.execute(
                "SELECT count(*) FROM reports WHERE published LIKE ? AND error IS NOT NULL", (f"{year}-%",)
            ).fetchone()[0]
            stats["scope"] = {
                row["city_scope"]: row["count"]
                for row in db.execute(
                    """SELECT city_scope,count(*) AS count FROM reports
                   WHERE published LIKE ? AND body IS NOT NULL GROUP BY city_scope""",
                    (f"{year}-%",),
                )
            }
            scan = db.execute("SELECT next_page,complete FROM archive_scan WHERE year=?", (year,)).fetchone()
            stats["archive_complete"] = bool(scan["complete"]) if scan else False
            stats["next_page"] = scan["next_page"] if scan else None
    finally:
        db.execute(
            "UPDATE runs SET finished=?,summary=? WHERE started=?", (time.time(), json.dumps(stats), started)
        )
        db.commit()
        db.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".runtime/safety/cities/essen/police.sqlite")
    parser.add_argument("--year", type=int, default=datetime.now(UTC).year)
    parser.add_argument("--full", action="store_true", help="resume a bounded full-year native archive scan")
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    import fcntl

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with open(args.db + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = sync(
            args.db, args.year, full=args.full, max_pages=args.max_pages, limit=args.limit, delay=args.delay
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failed"] or result["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
