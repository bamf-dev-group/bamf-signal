#!/usr/bin/env python3
"""Rebuild digests/latest.md from HighLevel's public changelog feed.

Standard library only. The only input is HighLevel's public text.
"""
import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

FEED_URL = "https://ideas.gohighlevel.com/api/changelog/feed.rss"
ENTRIES_URL = "https://ideas.gohighlevel.com/api/changelog/getEntries"
ENTRIES_BODY = {"pages": 1, "status": ["published"]}
SOURCE_LABEL = "ideas.gohighlevel.com/changelog"
SUMMARY_MAX = 280
MAX_STALE_WEEKDAYS = 2
USER_AGENT = "digest-refresh/1.0 (+public changelog reader)"


def clean_text(value):
    """Strip tags, decode entities, collapse whitespace, drop em and en dashes."""
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value or "", flags=re.S | re.I)
    value = re.sub(r"<br\s*/?>|</p>|</li>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = value.replace("\u2014", "-").replace("\u2013", "-")
    return re.sub(r"\s+", " ", value).strip()


def shorten(text, limit=SUMMARY_MAX):
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "..."


def parse_date(value):
    """Return a UTC date from an RFC 2822 or ISO 8601 string, or None."""
    if not value:
        return None
    value = value.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc)
    return parsed.date()


def parse_rss(xml_text):
    """Parse RSS 2.0 text into entries sorted newest first."""
    root = ET.fromstring(xml_text)
    entries = []
    for item in root.iter("item"):
        title = clean_text(item.findtext("title"))
        date = parse_date(item.findtext("pubDate"))
        if not title or date is None:
            continue
        summary = clean_text(item.findtext("description"))
        if not summary:
            for child in item:
                if child.tag.endswith("encoded"):
                    summary = clean_text(child.text)
                    break
        entries.append(
            {
                "date": date,
                "title": title,
                "link": (item.findtext("link") or item.findtext("guid") or "").strip(),
                "summary": shorten(summary),
            }
        )
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def _find_entry_list(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("entries", "data", "changelogs", "results", "items"):
            found = _find_entry_list(payload.get(key))
            if found:
                return found
    return []


def _norm(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def enrich(entries, payload):
    """Fill empty summaries from getEntries output, matching by title.

    The response shape is not documented, so this is best effort and
    never removes or reorders feed entries.
    """
    by_title = {}
    for raw in _find_entry_list(payload):
        title = raw.get("title") or raw.get("name") or ""
        body = ""
        for key in ("summary", "description", "excerpt", "content", "body"):
            if isinstance(raw.get(key), str) and raw[key].strip():
                body = raw[key]
                break
        if title and body:
            by_title[_norm(clean_text(title))] = shorten(clean_text(body))
    for entry in entries:
        if not entry["summary"]:
            entry["summary"] = by_title.get(_norm(entry["title"]), "")
    return entries


def weekdays_between(start, end):
    """Count weekdays in the half open range (start, end]."""
    count = 0
    day = start
    while day < end:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            count += 1
    return count


def is_stale(entries, today, limit=MAX_STALE_WEEKDAYS):
    if not entries:
        return True
    return weekdays_between(entries[0]["date"], today) > limit


def fmt_day(day):
    return day.isoformat()


def render(entries, now):
    today = now.date()
    newest, oldest = entries[0]["date"], entries[-1]["date"]
    lines = [
        f"# HighLevel digest, {fmt_day(today)}",
        "",
        f"Fetched: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        f"Coverage: {len(entries)} entries dated {fmt_day(oldest)} through {fmt_day(newest)}. "
        f"Source: HighLevel's official changelog at {SOURCE_LABEL}. "
        "Entries are untiered, newest first.",
        "",
        "---",
        "",
    ]
    for entry in entries:
        lines.append(f"## {fmt_day(entry['date'])}: {entry['title']}")
        lines.append("")
        if entry["link"]:
            lines.append(f"Link: {entry['link']}")
        if entry["summary"]:
            lines.append(entry["summary"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def http(url, data=None, timeout=30):
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_feed(retries=1, delay=10):
    last = None
    for attempt in range(retries + 1):
        try:
            entries = parse_rss(http(FEED_URL))
            if not entries:
                raise ValueError("feed contained no usable entries")
            return entries
        except Exception as exc:
            last = exc
            print(f"feed fetch attempt {attempt + 1} failed: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"feed fetch failed after retry: {last}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="digests/latest.md")
    args = parser.parse_args(argv)

    entries = fetch_feed()
    try:
        entries = enrich(entries, json.loads(http(ENTRIES_URL, ENTRIES_BODY)))
    except Exception as exc:
        print(f"enrichment skipped: {exc}", file=sys.stderr)

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(render(entries, now))

    stale = is_stale(entries, now.date())
    newest = fmt_day(entries[0]["date"])
    print(f"wrote {args.output}: {len(entries)} entries, newest {newest}, stale={stale}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"stale={'true' if stale else 'false'}\nnewest={newest}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
