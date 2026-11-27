#!/usr/bin/env python3
"""Rebuild digests/latest.md from HighLevel's public changelog.

Standard library only. The only inputs are HighLevel's public RSS feed, which holds the
newest 10 entries, and the public getEntries endpoint behind the changelog page, which is
paged back when the feed alone cannot reach the previous digest's newest entry.
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
SITE_URL = "https://ideas.gohighlevel.com"
MAX_ENTRY_PAGES = 20
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


def parse_datetime(value):
    """Return a UTC datetime without sub-seconds from RFC 2822, ISO 8601 or epoch input, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000 if value > 1e11 else value
        return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).replace(microsecond=0)
    value = str(value).strip()
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0)


def parse_date(value):
    """Return a UTC date from an RFC 2822 or ISO 8601 string, or None."""
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def parse_rss(xml_text):
    """Parse RSS 2.0 text into entries sorted newest first."""
    root = ET.fromstring(xml_text)
    entries = []
    for item in root.iter("item"):
        title = clean_text(item.findtext("title"))
        published = parse_datetime(item.findtext("pubDate"))
        if not title or published is None:
            continue
        summary = clean_text(item.findtext("description"))
        if not summary:
            for child in item:
                if child.tag.endswith("encoded"):
                    summary = clean_text(child.text)
                    break
        entries.append(
            {
                "date": published.date(),
                "published": published,
                "title": title,
                "link": (item.findtext("link") or item.findtext("guid") or "").strip(),
                "guid": (item.findtext("guid") or "").strip(),
                "summary": shorten(summary),
            }
        )
    entries.sort(key=lambda e: e["published"], reverse=True)
    return entries


def first_present(entry, keys):
    for key in keys:
        if entry.get(key) not in (None, "", [], {}):
            return entry[key]
    return None


def entry_from_api(raw):
    """Convert one getEntries entry to the same shape parse_rss returns, or None if unusable."""
    identifier = first_present(raw, ("id", "_id"))
    title = clean_text(str(first_present(raw, ("title",)) or ""))
    published = parse_datetime(first_present(raw, ("publishedAt", "published", "published_at", "created")))
    slug = first_present(raw, ("url", "urlName", "slug"))
    if not title or published is None or slug is None:
        return None
    slug = str(slug)
    link = slug if slug.startswith("http") else f"{SITE_URL}/changelog/{slug.strip('/').split('/')[-1]}"
    body = first_present(
        raw,
        ("plaintextDetails", "plaintext", "description", "html", "htmlDetails", "markdownDetails", "details"),
    )
    return {
        "date": published.date(),
        "published": published,
        "title": title,
        "link": link,
        "guid": str(identifier) if identifier is not None else "",
        "summary": shorten(clean_text(body if isinstance(body, str) else "")),
    }


def same_entry(a, b):
    """True when two entries are the same item: shared link or guid, else same title and second."""
    if a["link"] and a["link"] == b["link"]:
        return True
    if a["guid"] and a["guid"] == b["guid"]:
        return True
    return (
        html.unescape(a["title"]).casefold() == html.unescape(b["title"]).casefold()
        and a["published"] == b["published"]
    )


def merge_entries(primary, extra):
    """Add entries from extra that are not already in primary, newest first.

    A duplicate keeps the primary copy. When the two copies disagree on title or time,
    a warning goes to stderr and the primary copy still wins.
    """
    merged = list(primary)
    for entry in extra:
        match = next((p for p in merged if same_entry(p, entry)), None)
        if match is None:
            merged.append(entry)
        elif (
            html.unescape(match["title"]) != html.unescape(entry["title"])
            or match["published"] != entry["published"]
        ):
            print(
                f"cross-check: sources disagree on {match['link'] or match['guid']}: "
                f"{match['title']!r} {match['published'].isoformat()} vs "
                f"{entry['title']!r} {entry['published'].isoformat()}",
                file=sys.stderr,
            )
    merged.sort(key=lambda e: e["published"], reverse=True)
    return merged


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


NOT_SHIPPED_DEFAULT = (
    "## Not shipped, in case you heard otherwise\n\n"
    "Nothing recorded in this sweep.\n"
)
NOT_SHIPPED_RE = re.compile(r"^## Not shipped.*\Z", re.M | re.S)
COVERS_ISO_RE = re.compile(r"Covers entries dated \d{4}-\d{2}-\d{2} through (\d{4}-\d{2}-\d{2})")
COVERS_LEGACY_RE = re.compile(r"Covers entries dated .*? through ([A-Z][a-z]{2}) (\d{1,2}) (\d{4})")
WHAT_TO_DO = (
    "**What to do:** not tiered automatically. Open the link and check whether this changes "
    "anything live in your account before acting on it."
)


def previous_newest(text):
    """Newest entry date covered by the previous digest, or None."""
    match = COVERS_ISO_RE.search(text or "")
    if match:
        return dt.date.fromisoformat(match.group(1))
    match = COVERS_LEGACY_RE.search(text or "")
    if match:
        try:
            return dt.datetime.strptime(" ".join(match.groups()), "%b %d %Y").date()
        except ValueError:
            return None
    return None


def extract_not_shipped(text):
    match = NOT_SHIPPED_RE.search(text or "")
    return match.group(0).rstrip() + "\n" if match else NOT_SHIPPED_DEFAULT


def coverage_gap_line(entries, prev_newest):
    oldest = entries[-1]["date"]
    if prev_newest is None:
        return "Coverage gap: not computed, no previous digest on record."
    if oldest > prev_newest:
        return (
            f"Coverage gap: the feed's oldest entry ({fmt_day(oldest)}) is newer than the previous "
            f"digest's newest entry ({fmt_day(prev_newest)}), so entries between those dates may "
            "have been missed and are not reported here."
        )
    return "Coverage gap: none detected."


def render(entries, now, previous_text="", stale=None):
    """Render the digest. When stale, the title carries the newest entry date, not today."""
    today = now.date()
    newest, oldest = entries[0]["date"], entries[-1]["date"]
    if stale is None:
        stale = is_stale(entries, today)
    title_date = newest if stale else today
    lines = [
        f"# HighLevel digest, {fmt_day(title_date)}",
        "",
        f"Fetched: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        f"Covers entries dated {fmt_day(oldest)} through {fmt_day(newest)}. "
        f"Source: HighLevel's official changelog at {SOURCE_LABEL}.",
        "",
    ]
    if stale:
        lines += [
            f"STALE: the newest changelog entry ({fmt_day(newest)}) is more than "
            f"{MAX_STALE_WEEKDAYS} weekdays older than the fetch date ({fmt_day(today)}). "
            "Treat this digest as out of date.",
            "",
        ]
    lines += [
        coverage_gap_line(entries, previous_newest(previous_text)),
        "",
        f"0 HIGH, 0 MEDIUM, 0 LOW, {len(entries)} UNTIERED.",
        "",
        "---",
        "",
    ]
    for tier in ("HIGH", "MEDIUM", "LOW"):
        lines += [f"## {tier}", "", "None. Entries are not tiered automatically.", ""]
    lines += ["## UNTIERED", ""]
    for entry in entries:
        lines.append(f"### {entry['title']}")
        if entry["summary"]:
            lines.append(entry["summary"])
        lines.append(WHAT_TO_DO)
        if entry["link"]:
            lines.append(f"Link: {entry['link']}")
        lines += [f"{fmt_day(entry['date'])}.", ""]
    lines += ["---", "", extract_not_shipped(previous_text).rstrip(), ""]
    return "\n".join(lines)


def http(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_post(url, payload, timeout=30):
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    )
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


def fetch_api_entries(since, retries=1, delay=5, max_pages=MAX_ENTRY_PAGES):
    """Page getEntries until an entry dated before `since` appears or there is no next page.

    Works whether the endpoint returns the first N pages together or only page N, because
    the caller de-duplicates. Raises RuntimeError when a page cannot be fetched or parsed.
    """
    collected = []
    for pages in range(1, max_pages + 1):
        payload = json.dumps({"pages": pages, "status": ["published"]}).encode("utf-8")
        last = None
        for attempt in range(retries + 1):
            try:
                result = json.loads(http_post(ENTRIES_URL, payload))["result"]
                raw_entries, has_next = result["entries"], bool(result.get("hasNextPage"))
                if not isinstance(raw_entries, list):
                    raise ValueError("entries is not a list")
                break
            except Exception as exc:
                last = exc
                print(f"getEntries pages={pages} attempt {attempt + 1} failed: {exc}", file=sys.stderr)
                if attempt < retries:
                    time.sleep(delay)
        else:
            raise RuntimeError(f"getEntries failed after retry: {last}")
        entries = [e for e in (entry_from_api(r) for r in raw_entries if isinstance(r, dict)) if e]
        if pages == 1 and not entries:
            raise RuntimeError("getEntries returned no usable entries")
        collected = merge_entries(collected, entries)
        if not has_next or not entries or min(e["date"] for e in entries) < since:
            break
    return collected


def collect_entries(rss_entries, prev_newest, fetch_api=fetch_api_entries):
    """Combine the RSS items with getEntries items so the set reaches the previous digest.

    getEntries is only called when RSS alone does not reach prev_newest. If it fails, the RSS
    items are returned unchanged and the coverage gap line reports what is missing.
    """
    if prev_newest is None or rss_entries[-1]["date"] <= prev_newest:
        return rss_entries
    try:
        api_entries = fetch_api(prev_newest)
    except Exception as exc:
        print(f"getEntries unavailable, using the RSS feed only: {exc}", file=sys.stderr)
        return rss_entries
    return merge_entries(rss_entries, [e for e in api_entries if e["date"] >= prev_newest])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="digests/latest.md")
    parser.add_argument("--feed-file", help="read the feed from a local file instead of the network")
    parser.add_argument("--now", help="override the current UTC time, ISO 8601 (for tests)")
    args = parser.parse_args(argv)

    previous = ""
    if os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as fh:
            previous = fh.read()

    if args.feed_file:
        with open(args.feed_file, encoding="utf-8") as fh:
            entries = parse_rss(fh.read())
        if not entries:
            raise SystemExit("feed contained no usable entries")
    else:
        entries = collect_entries(fetch_feed(), previous_newest(previous))

    if args.now:
        now = dt.datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    else:
        now = dt.datetime.now(dt.timezone.utc)
    now = now.replace(microsecond=0)

    stale = is_stale(entries, now.date())
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(render(entries, now, previous, stale))

    newest = fmt_day(entries[0]["date"])
    print(f"wrote {args.output}: {len(entries)} entries, newest {newest}, stale={stale}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"stale={'true' if stale else 'false'}\nnewest={newest}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
