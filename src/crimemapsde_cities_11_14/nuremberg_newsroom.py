"""Bounded intake of the police-authored Mittelfranken Presseportal newsroom.

The publisher identity is checked in every article. The newsroom covers many
municipalities and roads; records remain pending and no map is produced here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx

from .nuremberg import LLM_SCOPE_EVIDENCE, city_scope

ORIGIN = "https://www.presseportal.de"
NEWSROOM = ORIGIN + "/blaulicht/nr/6013"
PUBLISHER = "Polizeipräsidium Mittelfranken"
USER_AGENT = "CrimeMapsDE-Cities-11-14/0.1 (Nuremberg police newsroom index)"
ARTICLE_PATH = re.compile(r"/blaulicht/pm/6013/(\d+)$")
PAGE_PATH = re.compile(r"/blaulicht/nr/6013(?:/\d+)?$")
NEXT_PAGE = re.compile(r'<link\s+rel="next"\s+href="([^"]+)"')
SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL, published TEXT NOT NULL,
 district TEXT NOT NULL DEFAULT '', body TEXT, sha256 TEXT, etag TEXT, modified TEXT,
 checked REAL, retry_after REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
 error TEXT, first_seen REAL NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 city_scope TEXT NOT NULL DEFAULT 'needs_review', scope_evidence TEXT NOT NULL DEFAULT '',
 review_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS revisions (
 id TEXT NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL, observed REAL NOT NULL,
 PRIMARY KEY(id, revision)
);
CREATE TABLE IF NOT EXISTS runs (started REAL PRIMARY KEY, finished REAL, summary TEXT);
CREATE TABLE IF NOT EXISTS archive_cursor (
 year INTEGER PRIMARY KEY, next_url TEXT, pages_scanned INTEGER NOT NULL,
 complete INTEGER NOT NULL, updated REAL NOT NULL
);
"""


class NewsroomParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.articles_seen = 0
        self.current = None
        self.field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "article" and "news" in classes:
            self.articles_seen += 1
            if attrs.get("data-label", "").isdigit():
                self.current = {
                    "id": attrs["data-label"],
                    "url": "",
                    "title": "",
                    "published": "",
                    "district": "",
                }
        if self.current is None:
            return
        if tag == "div" and "date" in classes:
            self.field = "published"
        elif tag == "h3" and "news-headline-clamp" in classes:
            self.field = "title"
        elif tag == "a" and self.field == "title":
            url = urljoin(ORIGIN, attrs.get("href", ""))
            parsed = urlparse(url)
            match = ARTICLE_PATH.fullmatch(parsed.path)
            if (
                parsed.scheme == "https"
                and parsed.netloc == "www.presseportal.de"
                and not parsed.query
                and not parsed.fragment
                and match
                and match[1] == self.current["id"]
            ):
                self.current["url"] = url

    def handle_data(self, data):
        if self.current is not None and self.field:
            self.current[self.field] += data

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag in {"div", "h3"}:
            self.field = None
        elif tag == "article":
            row = self.current
            if row["url"] and row["title"] and row["published"]:
                # Presseportal displays German local time without an explicit offset.
                row["published"] = datetime.strptime(
                    " ".join(row["published"].replace("–", " ").split()),
                    "%d.%m.%Y %H:%M",
                ).replace(tzinfo=ZoneInfo("Europe/Berlin")).isoformat()
                row["title"] = " ".join(row["title"].split())
                self.rows.append(row)
            self.current = None
            self.field = None


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_story = False
        self.after_heading = False
        self.current_tag = None
        self.stopped = False
        self.parts = []
        self.current = []
        self.in_customer = False
        self.customer = ""

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag == "article" and "story" in classes:
            self.in_story = True
        elif self.in_story and tag == "p" and "customer" in classes:
            self.in_customer = True
        elif self.in_story and self.after_heading and tag in {"p", "li"}:
            if "contact-headline" in classes or "originator" in classes:
                self.stopped = True
            elif not self.stopped and self.current_tag is None:
                self.current_tag = tag
                self.current = []

    def handle_data(self, data):
        if self.in_customer:
            self.customer += data
        if self.current_tag is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if not self.in_story:
            return
        if tag == "h1":
            self.after_heading = True
        elif tag in {"p", "li"}:
            if tag == "p":
                self.in_customer = False
            if self.current_tag == tag:
                paragraph = " ".join(" ".join(self.current).split())
                if paragraph and not paragraph.startswith("Schneller informiert:"):
                    self.parts.append(paragraph)
                self.current_tag = None
        elif tag == "article":
            self.in_story = False


def listing_rows(page):
    parser = NewsroomParser()
    parser.feed(page)
    if parser.articles_seen == 0 or parser.articles_seen != len(parser.rows):
        raise ValueError("Nuremberg newsroom list contains no or unparsed articles")
    if [row["published"] for row in parser.rows] != sorted(
        (row["published"] for row in parser.rows), reverse=True
    ):
        raise ValueError("Nuremberg newsroom order changed")
    return parser.rows


def article_body(page):
    parser = ArticleParser()
    parser.feed(page)
    body = " ".join(parser.parts)
    if parser.customer.strip() != PUBLISHER or len(body) < 30:
        raise ValueError("Nuremberg article parser or publisher check failed")
    return body


def next_url(page):
    match = NEXT_PAGE.search(page)
    if not match:
        return None
    url = urljoin(ORIGIN, match[1])
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.presseportal.de"
        or parsed.query
        or parsed.fragment
        or not PAGE_PATH.fullmatch(parsed.path)
    ):
        raise ValueError("Unexpected Nuremberg newsroom pagination link")
    return url


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    existing = {row["name"] for row in db.execute("PRAGMA table_info(reports)")}
    if existing and not {
        "id", "url", "title", "published", "body", "sha256", "revision",
        "checked", "city_scope", "scope_evidence", "review_status",
    } <= existing:
        db.close()
        raise ValueError("Nuremberg newsroom needs its own SQLite database")
    db.executescript(SCHEMA)
    db.execute(
        """UPDATE reports SET city_scope='needs_review',scope_evidence=?,review_status='pending'
           WHERE body IS NOT NULL AND (city_scope<>'needs_review' OR scope_evidence<>?)""",
        (LLM_SCOPE_EVIDENCE, LLM_SCOPE_EVIDENCE),
    )
    db.commit()
    db.execute("PRAGMA journal_mode=WAL")
    return db


def discover(db: sqlite3.Connection, rows: list[dict], now: float) -> None:
    for row in rows:
        db.execute(
            """INSERT INTO reports(id,url,title,published,district,first_seen)
               VALUES(:id,:url,:title,:published,:district,:now)
               ON CONFLICT(id) DO UPDATE SET url=excluded.url,title=excluded.title,
               published=excluded.published,
               checked=CASE WHEN reports.url<>excluded.url OR reports.title<>excluded.title OR
               reports.published<>excluded.published THEN NULL ELSE reports.checked END,
               review_status=CASE WHEN reports.url<>excluded.url OR reports.title<>excluded.title OR
               reports.published<>excluded.published THEN 'pending' ELSE reports.review_status END""",
            {**row, "now": now},
        )
    db.commit()


def accept(db: sqlite3.Connection, ident: str, body: str, headers: dict, now: float) -> str:
    body = " ".join(body.split())
    if len(body) < 30:
        raise ValueError("Nuremberg article body extraction failed")
    row = db.execute("SELECT * FROM reports WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise ValueError("Nuremberg article was not discovered")
    digest = hashlib.sha256(body.encode()).hexdigest()
    changed = row["sha256"] != digest
    revision = row["revision"] + int(changed)
    scope, evidence = city_scope(row["title"], body)
    db.execute(
        """UPDATE reports SET body=?,sha256=?,etag=?,modified=?,checked=?,error=NULL,
           retry_after=0,failures=0,revision=?,city_scope=?,scope_evidence=?,
           review_status=CASE WHEN ? THEN 'pending' ELSE review_status END WHERE id=?""",
        (
            body,
            digest,
            headers.get("etag"),
            headers.get("last-modified"),
            now,
            revision,
            scope,
            evidence,
            int(changed or row["city_scope"] != scope or row["scope_evidence"] != evidence),
            ident,
        ),
    )
    if changed:
        db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (ident, revision, digest, now))
    db.commit()
    return "new" if row["sha256"] is None else "revised" if changed else "unchanged"


def fail(db: sqlite3.Connection, ident: str, error: str, now: float, status: int | None = None) -> None:
    row = db.execute("SELECT failures FROM reports WHERE id=?", (ident,)).fetchone()
    failures = row[0] + 1
    retry_after = now + min(86400, 300 * 2 ** min(failures - 1, 8))
    db.execute(
        "UPDATE reports SET failures=?,error=?,retry_after=? WHERE id=?",
        (failures, f"{error}; http_status={status}"[:200], retry_after, ident),
    )
    db.commit()


def completed_traversal(db: sqlite3.Connection, year: int, state: sqlite3.Row | None) -> tuple[bool, int]:
    """Return sticky newsroom completion, including recovery from the old reset bug."""
    scanned = state["pages_scanned"] if state else 0
    if state and state["complete"]:
        return True, scanned
    for row in db.execute(
        "SELECT summary FROM runs WHERE summary IS NOT NULL ORDER BY started DESC"
    ):
        try:
            summary = json.loads(row["summary"])
        except (TypeError, json.JSONDecodeError):
            continue
        if summary.get("year") == year and summary.get("newsroom_scan_complete") is True:
            return True, max(scanned, int(summary.get("cursor_pages_scanned", 0)))
    return False, scanned


def sync(path, year, *, pages=1, limit=5, delay=1.0):
    """Scan at most ``pages`` archive pages and revisit at most ``limit`` articles.

    A bounded run is a checkpoint, not a complete-year coverage claim.
    """
    if (
        not 2015 <= year <= datetime.now(UTC).year
        or not 1 <= pages <= 10
        or not 1 <= limit <= 30
        or delay < 1
    ):
        raise ValueError("Use available year, bounded page/article counts and delay >= 1 second")
    db = connect(path)
    started = time.time()
    stats = {
        "year": year,
        "requested_pages": pages,
        "archive_pages": 0,
        "head_refreshed": False,
        "discovered": 0,
        "new": 0,
        "revised": 0,
        "unchanged": 0,
        "failed": 0,
        "archive_exhausted": False,
        "year_covered": False,
    }
    db.execute("INSERT INTO runs(started) VALUES(?)", (started,))
    db.commit()
    try:
        with httpx.Client(
            timeout=25,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            for attempt in range(3):
                try:
                    robots_response = client.get(ORIGIN + "/robots.txt")
                    if robots_response.status_code == 429:
                        robots_response.raise_for_status()
                    robots_response.raise_for_status()
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                        raise
                    if attempt == 2:
                        raise
                    time.sleep(2**attempt)
            robots_response.raise_for_status()
            if (
                robots_response.status_code != 200
                or str(robots_response.url) != ORIGIN + "/robots.txt"
                or not re.search(r"(?im)^\s*user-agent:\s*\*\s*$", robots_response.text)
                or robots_response.text.lstrip().startswith("<")
                or not robots_response.headers.get("content-type", "").lower().startswith("text/plain")
            ):
                raise ValueError("Missing or unexpected Nuremberg newsroom robots.txt")
            robots = RobotFileParser()
            robots.parse(robots_response.text.splitlines())
            delay = max(delay, float(robots.crawl_delay(USER_AGENT) or 0))
            request_rate = robots.request_rate(USER_AGENT)
            if request_rate:
                if request_rate.requests <= 0:
                    raise ValueError("Invalid Nuremberg newsroom robots request rate")
                delay = max(delay, request_rate.seconds / request_rate.requests)
            last_request = time.monotonic()

            def get(url, headers=None):
                nonlocal last_request
                expected_path = urlparse(url).path
                for _ in range(4):
                    parsed = urlparse(url)
                    if parsed.scheme != "https" or parsed.netloc != "www.presseportal.de":
                        raise ValueError("Unexpected Nuremberg newsroom origin")
                    if (
                        parsed.query or parsed.fragment
                        or not (PAGE_PATH.fullmatch(parsed.path) or ARTICLE_PATH.fullmatch(parsed.path))
                    ):
                        raise ValueError("Unexpected Nuremberg newsroom path")
                    if not robots.can_fetch(USER_AGENT, url):
                        raise ValueError("robots.txt disallows " + url)
                    for attempt in range(3):
                        time.sleep(max(0, delay - (time.monotonic() - last_request)))
                        last_request = time.monotonic()
                        try:
                            response = client.get(url, headers=headers)
                        except httpx.TransportError:
                            if attempt == 2:
                                raise
                            time.sleep(2**attempt)
                            continue
                        if response.status_code == 429:
                            response.raise_for_status()
                        if response.status_code in {500, 502, 503, 504}:
                            if attempt == 2:
                                response.raise_for_status()
                            retry_after = response.headers.get("retry-after", "")
                            wait = int(retry_after) if retry_after.isdigit() else 2**attempt
                            time.sleep(min(30, max(delay, wait)))
                            continue
                        break
                    if response.status_code in (301, 302, 303, 307, 308):
                        target = urljoin(str(response.url), response.headers["location"])
                        if urlparse(target).path != expected_path:
                            raise ValueError("Nuremberg newsroom redirect changed record path")
                        url = target
                        continue
                    if response.status_code != 304:
                        response.raise_for_status()
                    return response
                raise ValueError("Too many Nuremberg newsroom redirects")

            seen_ids = set()

            def scan(url):
                page = get(url).text
                rows = listing_rows(page)
                following = next_url(page)
                if len(rows) == 30 and following is None:
                    raise ValueError("Full Nuremberg newsroom page lost its pagination link")
                selected = [r for r in rows if r["published"].startswith(str(year))]
                discover(db, selected, time.time())
                seen_ids.update(r["id"] for r in selected)
                stats["discovered"] = len(seen_ids)
                stats["archive_pages"] += 1
                return rows, following

            state = db.execute(
                "SELECT next_url,pages_scanned,complete FROM archive_cursor WHERE year=?", (year,)
            ).fetchone()
            traversal_complete, scanned = completed_traversal(db, year, state)
            cursor = state["next_url"] if state and not traversal_complete else NEWSROOM
            if traversal_complete:
                scan(NEWSROOM)
                stats["head_refreshed"] = True
                db.execute(
                    """INSERT INTO archive_cursor(year,next_url,pages_scanned,complete,updated)
                       VALUES(?,?,?,?,?) ON CONFLICT(year) DO UPDATE SET
                       next_url=excluded.next_url,pages_scanned=excluded.pages_scanned,
                       complete=excluded.complete,updated=excluded.updated""",
                    (year, None, scanned, 1, time.time()),
                )
                db.commit()
            elif cursor != NEWSROOM:
                scan(NEWSROOM)
                stats["head_refreshed"] = True
            if not traversal_complete:
                url = cursor
                seen_pages = set()
                for _ in range(pages):
                    if url in seen_pages:
                        raise ValueError("Nuremberg newsroom pagination loop")
                    seen_pages.add(url)
                    rows, url = scan(url)
                    scanned += 1
                    if url is None:
                        stats["archive_exhausted"] = True
                    if all(r["published"][:4] < str(year) for r in rows):
                        stats["year_covered"] = True
                    complete = stats["archive_exhausted"] or stats["year_covered"]
                    db.execute(
                        """INSERT INTO archive_cursor(year,next_url,pages_scanned,complete,updated)
                           VALUES(?,?,?,?,?) ON CONFLICT(year) DO UPDATE SET
                           next_url=excluded.next_url,pages_scanned=excluded.pages_scanned,
                           complete=excluded.complete,updated=excluded.updated""",
                        (year, url, scanned, int(complete), time.time()),
                    )
                    db.commit()
                    if complete:
                        break
            stats["newsroom_scan_complete"] = bool(
                db.execute("SELECT complete FROM archive_cursor WHERE year=?", (year,)).fetchone()[0]
            )
            # The publisher feed need not match the blocked native archive.
            stats["archive_complete"] = False
            stats["cursor_pages_scanned"] = scanned
            pending = db.execute(
                """SELECT * FROM reports WHERE published LIKE ? AND retry_after<=? AND
                   (body IS NULL OR checked IS NULL OR checked<? OR published>=?)
                   ORDER BY body IS NOT NULL, COALESCE(checked,0), published DESC LIMIT ?""",
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
                    response = get(row["url"], headers)
                    if response.status_code == 304:
                        if row["body"] is None:
                            raise ValueError("304 without cached body")
                        db.execute(
                            "UPDATE reports SET checked=?,error=NULL,failures=0,retry_after=0 WHERE id=?",
                            (time.time(), row["id"]),
                        )
                        db.commit()
                        result = "unchanged"
                    else:
                        result = accept(
                            db, row["id"], article_body(response.text), response.headers, time.time()
                        )
                    stats[result] += 1
                except (httpx.HTTPError, ValueError) as exc:
                    status = (
                        exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                    )
                    fail(
                        db,
                        row["id"],
                        f"{type(exc).__name__}: {exc}",
                        time.time(),
                        status,
                    )
                    stats["failed"] += 1
                    if status == 429:
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
                r["city_scope"]: r["count"]
                for r in db.execute(
                    "SELECT city_scope,count(*) AS count FROM reports WHERE published LIKE ? AND body IS NOT NULL GROUP BY city_scope",
                    (f"{year}-%",),
                )
            }
    except Exception as exc:
        stats["fatal_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        db.execute(
            "UPDATE runs SET finished=?,summary=? WHERE started=?", (time.time(), json.dumps(stats), started)
        )
        db.commit()
        db.close()
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".runtime/safety/cities/nuremberg/newsroom.sqlite")
    parser.add_argument("--year", type=int, default=datetime.now(UTC).year)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if (
        args.year < 2015
        or args.year > datetime.now(UTC).year
        or not 1 <= args.pages <= 10
        or not 1 <= args.limit <= 30
        or args.delay < 1
    ):
        parser.error("Use available year, 1–10 pages, 1–30 articles and delay >= 1 second")
    import fcntl

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with open(args.db + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = sync(args.db, args.year, pages=args.pages, limit=args.limit, delay=args.delay)
    print(json.dumps(result, indent=2))
    if result["failed"] or result["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
