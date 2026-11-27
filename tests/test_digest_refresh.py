import datetime as dt
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import digest_refresh as dr  # noqa: E402

FIXTURE = (ROOT / "tests" / "fixtures" / "changelog.rss").read_text(encoding="utf-8")
NOW = dt.datetime(2026, 11, 20, 11, 40, 5, tzinfo=dt.timezone.utc)


class ParseTests(unittest.TestCase):
    def test_sorted_newest_first_and_undated_skipped(self):
        entries = dr.parse_rss(FIXTURE)
        self.assertEqual(
            [e["title"] for e in entries],
            ["Newest feature - now live", "No summary entry", "Older & simpler update"],
        )

    def test_summary_is_plain_text(self):
        entries = dr.parse_rss(FIXTURE)
        self.assertEqual(entries[0]["summary"], "First line. Second point")
        self.assertEqual(entries[2]["summary"], "Plain older summary.")

    def test_dashes_removed(self):
        text = dr.clean_text("a \u2014 b \u2013 c")
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)

    def test_shorten(self):
        out = dr.shorten("word " * 100, 50)
        self.assertLessEqual(len(out), 53)
        self.assertTrue(out.endswith("..."))


PREVIOUS = (ROOT / "tests" / "fixtures" / "previous_latest.md").read_text(encoding="utf-8")


PREVIOUS = (ROOT / "tests" / "fixtures" / "previous_latest.md").read_text(encoding="utf-8")


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.entries = dr.parse_rss(FIXTURE)
        self.out = dr.render(self.entries, NOW, PREVIOUS)
        self.lines = self.out.splitlines()

    def test_title_and_fetched_lines(self):
        self.assertEqual(self.lines[0], "# HighLevel digest, 2026-11-20")
        self.assertIn("Fetched: 2026-11-20T11:40:05Z", self.lines)

    def test_covers_line(self):
        self.assertTrue(
            any(l.startswith("Covers entries dated 2026-11-17 through 2026-11-19.") for l in self.lines)
        )

    def test_tier_counts_reflect_untiered(self):
        self.assertIn("0 HIGH, 0 MEDIUM, 0 LOW, 3 UNTIERED.", self.lines)

    def test_all_tier_headers_present_in_order(self):
        order = [self.out.index(h) for h in ("## HIGH", "## MEDIUM", "## LOW", "## UNTIERED")]
        self.assertEqual(order, sorted(order))

    def test_entries_newest_first_with_what_to_do_and_link(self):
        self.assertIn("### Newest feature - now live", self.lines)
        self.assertIn("First line. Second point", self.lines)
        self.assertIn("Link: https://ideas.gohighlevel.com/changelog/newest-feature", self.lines)
        self.assertEqual(sum(l.startswith("**What to do:**") for l in self.lines), 3)
        self.assertIn("2026-11-19.", self.lines)
        self.assertLess(self.out.index("### Newest feature"), self.out.index("### Older"))

    def test_not_shipped_carried_forward_last(self):
        self.assertIn("## Not shipped, in case you heard otherwise", self.lines)
        self.assertIn("Project/Task Organizer Like Asana", self.out)
        self.assertGreater(self.out.index("## Not shipped"), self.out.index("## UNTIERED"))

    def test_not_shipped_default_without_previous(self):
        out = dr.render(self.entries, NOW, "")
        self.assertIn("## Not shipped, in case you heard otherwise", out)

    def test_not_stale_has_no_stale_line(self):
        self.assertNotIn("STALE:", self.out)

    def test_idempotent_not_shipped_across_runs(self):
        again = dr.render(self.entries, NOW, self.out)
        self.assertEqual(dr.extract_not_shipped(again), dr.extract_not_shipped(self.out))

    def test_no_dashes(self):
        self.assertNotIn("\u2014", self.out)
        self.assertNotIn("\u2013", self.out)


class StaleRenderTests(unittest.TestCase):
    def test_stale_title_uses_newest_entry_date_not_today(self):
        entries = dr.parse_rss(FIXTURE)
        later = dt.datetime(2026, 11, 25, 11, 40, 0, tzinfo=dt.timezone.utc)
        out = dr.render(entries, later, PREVIOUS)
        lines = out.splitlines()
        self.assertEqual(lines[0], "# HighLevel digest, 2026-11-19")
        self.assertIn("Fetched: 2026-11-25T11:40:00Z", lines)
        self.assertTrue(any(l.startswith("STALE:") for l in lines))
        self.assertNotIn("2026-11-25", lines[0])


class CoverageGapTests(unittest.TestCase):
    def setUp(self):
        self.entries = dr.parse_rss(FIXTURE)

    def test_gap_when_oldest_newer_than_previous_newest(self):
        # Fixture oldest is 2026-11-17; previous digest newest is Aug 26 2026.
        line = dr.coverage_gap_line(self.entries, dt.date(2026, 8, 26))
        self.assertTrue(line.startswith("Coverage gap: the feed's oldest entry (2026-11-17)"))

    def test_no_gap_when_feed_reaches_previous_newest(self):
        line = dr.coverage_gap_line(self.entries, dt.date(2026, 11, 18))
        self.assertEqual(line, "Coverage gap: none detected.")

    def test_not_computed_without_previous(self):
        line = dr.coverage_gap_line(self.entries, None)
        self.assertTrue(line.startswith("Coverage gap: not computed"))

    def test_previous_newest_parses_legacy_and_iso(self):
        self.assertEqual(dr.previous_newest(PREVIOUS), dt.date(2026, 8, 26))
        rendered = dr.render(self.entries, NOW, PREVIOUS)
        self.assertEqual(dr.previous_newest(rendered), dt.date(2026, 11, 19))
        self.assertIsNone(dr.previous_newest(""))


class MainTests(unittest.TestCase):
    def run_main(self, now, previous=PREVIOUS):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "latest.md"
            out.write_text(previous, encoding="utf-8")
            feed = str(ROOT / "tests" / "fixtures" / "changelog.rss")
            env = pathlib.Path(tmp) / "gh_output"
            old = os.environ.get("GITHUB_OUTPUT")
            os.environ["GITHUB_OUTPUT"] = str(env)
            try:
                dr.main(["--output", str(out), "--feed-file", feed, "--now", now])
            finally:
                if old is None:
                    del os.environ["GITHUB_OUTPUT"]
                else:
                    os.environ["GITHUB_OUTPUT"] = old
            return out.read_text(encoding="utf-8"), env.read_text(encoding="utf-8")

    def test_fresh_run_writes_today_and_reports_not_stale(self):
        text, outputs = self.run_main("2026-11-20T11:40:05Z")
        self.assertTrue(text.startswith("# HighLevel digest, 2026-11-20"))
        self.assertIn("stale=false", outputs)

    def test_stale_run_reports_stale_and_keeps_entry_date(self):
        text, outputs = self.run_main("2026-11-26T11:40:05Z")
        self.assertTrue(text.startswith("# HighLevel digest, 2026-11-19"))
        self.assertIn("Fetched: 2026-11-26T11:40:05Z", text)
        self.assertIn("stale=true", outputs)
        self.assertIn("newest=2026-11-19", outputs)


def rss_item(title, link, stamp, guid=None):
    guid_xml = f"<guid isPermaLink=\"false\">{guid}</guid>" if guid else ""
    return (
        f"<item><title>{title}</title><link>{link}</link>{guid_xml}"
        f"<pubDate>{stamp}</pubDate><description>Body of {link}</description></item>"
    )


def rss_feed(items):
    return f"<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>{''.join(items)}</channel></rss>"


def api_entry(n, published, title=None, url=None):
    return {
        "id": f"id{n}",
        "title": title or f"Entry {n}",
        "publishedAt": published,
        "url": url or f"entry-{n}",
        "plaintextDetails": f"Body of entry {n}",
    }


class FakeEntriesApi:
    """getEntries stand-in: page size 10, and `pages` returns the first N pages together."""

    def __init__(self, entries, page_size=10):
        self.entries = entries
        self.page_size = page_size
        self.calls = []

    def __call__(self, url, payload, timeout=30):
        body = json.loads(payload)
        self.calls.append(body)
        count = body["pages"] * self.page_size
        shown = self.entries[:count]
        return json.dumps({"result": {"entries": shown, "hasNextPage": count < len(self.entries)}})


PREV_DIGEST = (
    "# HighLevel digest, 2026-11-26\n\n"
    "Covers entries dated 2026-11-24 through 2026-11-26. Source: x.\n\n"
    "## Not shipped, in case you heard otherwise\n\nNothing recorded in this sweep.\n"
)
BUSY_NOW = "2026-11-27T20:15:30Z"


def busy_day_entries():
    """12 entries on 2026-11-27 (newest first), then two on 11-26 and two on 11-25."""
    entries = []
    for n in range(12):
        entries.append(api_entry(n, f"2026-11-27T{20 - n:02d}:00:00.123Z"))
    entries.append(api_entry(12, "2026-11-26T15:00:00Z"))
    entries.append(api_entry(13, "2026-11-26T09:00:00Z"))
    entries.append(api_entry(14, "2026-11-25T15:00:00Z"))
    entries.append(api_entry(15, "2026-11-25T09:00:00Z"))
    return entries


def busy_day_rss(entries, count=10):
    return rss_feed(
        rss_item(
            e["title"],
            f"https://ideas.gohighlevel.com/changelog/{e['url']}",
            dr.parse_datetime(e["publishedAt"]).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            guid=e["id"],
        )
        for e in entries[:count]
    )


class GetEntriesTests(unittest.TestCase):
    def run_main(self, rss_text, api, previous=PREV_DIGEST, now=BUSY_NOW):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "latest.md"
            out.write_text(previous, encoding="utf-8")
            stderr = io.StringIO()
            with mock.patch.object(dr, "http", return_value=rss_text), mock.patch.object(
                dr, "http_post", api
            ), mock.patch.object(dr.time, "sleep"), redirect_stderr(stderr):
                dr.main(["--output", str(out), "--now", now])
            return out.read_text(encoding="utf-8"), stderr.getvalue()

    def test_busy_day_over_ten_entries_closes_the_gap(self):
        entries = busy_day_entries()
        api = FakeEntriesApi(entries)
        text, _ = self.run_main(busy_day_rss(entries), api)
        self.assertIn("Coverage gap: none detected.", text)
        self.assertNotIn("is newer than the previous", text)
        for n in range(12):
            self.assertEqual(text.count(f"### Entry {n}\n"), 1, n)
        self.assertIn("### Entry 12\n", text)
        self.assertIn("### Entry 13\n", text)
        self.assertNotIn("### Entry 14\n", text)
        self.assertIn("0 HIGH, 0 MEDIUM, 0 LOW, 14 UNTIERED.", text)
        self.assertIn("Covers entries dated 2026-11-26 through 2026-11-27.", text)
        self.assertEqual([c["pages"] for c in api.calls], [1, 2])
        self.assertIn("Link: https://ideas.gohighlevel.com/changelog/entry-11", text)
        self.assertLess(text.index("### Entry 0\n"), text.index("### Entry 11\n"))

    def test_getentries_failure_falls_back_to_rss_and_prints_gap(self):
        entries = busy_day_entries()

        def broken(url, payload, timeout=30):
            raise urllib.error.URLError("blocked")

        text, err = self.run_main(busy_day_rss(entries), broken)
        self.assertIn("getEntries unavailable, using the RSS feed only", err)
        self.assertIn(
            "Coverage gap: the feed's oldest entry (2026-11-27) is newer than the previous "
            "digest's newest entry (2026-11-26)",
            text,
        )
        self.assertIn("0 HIGH, 0 MEDIUM, 0 LOW, 10 UNTIERED.", text)

    def test_getentries_bad_reply_falls_back_to_rss(self):
        entries = busy_day_entries()
        for reply in ("not json", json.dumps({"result": {}}), json.dumps({"result": {"entries": []}})):
            text, err = self.run_main(busy_day_rss(entries), lambda url, payload, timeout=30, r=reply: r)
            self.assertIn("using the RSS feed only", err)
            self.assertIn("Coverage gap: the feed's oldest entry", text)

    def test_gap_line_stays_when_combined_set_still_short(self):
        entries = busy_day_entries()[:14]
        api = FakeEntriesApi(entries)
        text, _ = self.run_main(busy_day_rss(entries), api, previous=PREV_DIGEST.replace("2026-11-26.", "2026-11-24."))
        self.assertIn("Coverage gap: the feed's oldest entry (2026-11-26)", text)
        self.assertIn("previous digest's newest entry (2026-11-24)", text)

    def test_rss_that_already_reaches_previous_skips_getentries(self):
        entries = busy_day_entries()[10:]
        api = FakeEntriesApi(entries)
        text, _ = self.run_main(busy_day_rss(entries, count=4), api)
        self.assertEqual(api.calls, [])
        self.assertIn("Coverage gap: none detected.", text)

    def test_dedupe_across_both_sources(self):
        rss_entries = [
            dr.parse_rss(
                rss_feed(
                    [
                        rss_item(
                            "Same link",
                            "https://ideas.gohighlevel.com/changelog/same-link",
                            "Fri, 27 Nov 2026 10:00:00 GMT",
                        ),
                        rss_item(
                            "Same guid",
                            "https://ideas.gohighlevel.com/changelog/same-guid",
                            "Fri, 27 Nov 2026 09:00:00 GMT",
                            guid="guid-2",
                        ),
                        rss_item(
                            "Fish &amp;amp; Chips",
                            "https://ideas.gohighlevel.com/changelog/old-slug",
                            "Fri, 27 Nov 2026 08:00:00 GMT",
                        ),
                    ]
                )
            )
        ][0]
        api_entries = dr.merge_entries(
            [],
            [
                dr.entry_from_api(
                    {"id": "a", "title": "Same link", "publishedAt": "2026-11-27T10:00:00.900Z", "url": "same-link"}
                ),
                dr.entry_from_api(
                    {"id": "guid-2", "title": "Same guid", "publishedAt": "2026-11-27T09:00:00Z", "url": "renamed"}
                ),
                dr.entry_from_api(
                    {"id": "c", "title": "Fish & Chips", "publishedAt": "2026-11-27T08:00:00.450Z", "url": "new-slug"}
                ),
                dr.entry_from_api(
                    {"id": "d", "title": "Only in API", "publishedAt": "2026-11-26T08:00:00Z", "url": "api-only"}
                ),
            ],
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            merged = dr.merge_entries(rss_entries, api_entries)
        self.assertEqual(
            [e["title"] for e in merged], ["Same link", "Same guid", "Fish & Chips", "Only in API"]
        )
        self.assertEqual(sum(e["link"].endswith("/same-link") for e in merged), 1)
        self.assertEqual(stderr.getvalue(), "")

    def test_dedupe_end_to_end_overlapping_sources(self):
        entries = busy_day_entries()
        text, _ = self.run_main(busy_day_rss(entries), FakeEntriesApi(entries))
        titles = [l for l in text.splitlines() if l.startswith("### ")]
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(len(titles), 14)

    def test_disagreement_between_sources_is_warned_and_rss_wins(self):
        rss = dr.parse_rss(
            rss_feed([rss_item("Title A", "https://ideas.gohighlevel.com/changelog/x", "Fri, 27 Nov 2026 10:00:00 GMT")])
        )
        api = [dr.entry_from_api({"id": "1", "title": "Title B", "publishedAt": "2026-11-27T10:00:05Z", "url": "x"})]
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            merged = dr.merge_entries(rss, api)
        self.assertEqual([e["title"] for e in merged], ["Title A"])
        self.assertIn("cross-check: sources disagree", stderr.getvalue())

    def test_sub_seconds_are_dropped(self):
        parsed = dr.parse_datetime("2026-11-27T10:00:00.987Z")
        self.assertEqual(parsed, dt.datetime(2026, 11, 27, 10, 0, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(
            dr.parse_datetime(1795773600123), dt.datetime(2026, 11, 27, 10, 0, 0, tzinfo=dt.timezone.utc)
        )

    def test_api_titles_are_unescaped(self):
        entry = dr.entry_from_api({"id": "1", "title": "A &amp; B", "publishedAt": "2026-11-27T10:00:00Z", "url": "a"})
        self.assertEqual(entry["title"], "A & B")


class FreshnessTests(unittest.TestCase):
    def e(self, y, m, d):
        return [{"date": dt.date(y, m, d)}]

    def test_weekday_count_skips_weekend(self):
        # Fri 2026-11-20 to Mon 2026-11-23 is one weekday.
        self.assertEqual(dr.weekdays_between(dt.date(2026, 11, 20), dt.date(2026, 11, 23)), 1)

    def test_fresh_within_two_weekdays(self):
        self.assertFalse(dr.is_stale(self.e(2026, 11, 20), dt.date(2026, 11, 24)))

    def test_stale_after_two_weekdays(self):
        self.assertTrue(dr.is_stale(self.e(2026, 11, 20), dt.date(2026, 11, 25)))

    def test_empty_is_stale(self):
        self.assertTrue(dr.is_stale([], dt.date(2026, 11, 25)))


class RepoRuleTests(unittest.TestCase):
    def test_actions_pinned_to_shas(self):
        for name in ("digest-refresh.yml", "test.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            uses = [l.split("uses:")[1].strip() for l in text.splitlines() if "uses:" in l]
            self.assertTrue(uses)
            for ref in uses:
                self.assertRegex(ref, r"^actions/[a-z-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")

    def test_refresh_workflow_permissions_and_inputs(self):
        text = (ROOT / ".github" / "workflows" / "digest-refresh.yml").read_text(encoding="utf-8")
        for needle in ("contents: write", "issues: write", "dry_run", "git pull --rebase", "40 11 * * 1-5"):
            self.assertIn(needle, text)

    def test_no_pyc_tracked_and_gitignore(self):
        self.assertIn("__pycache__/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_no_em_or_en_dashes_in_repo_files(self):
        paths = [
            ROOT / "README.md",
            ROOT / ".github" / "workflows" / "digest-refresh.yml",
            ROOT / "scripts" / "digest_refresh.py",
            ROOT / "tests" / "test_digest_refresh.py",
            ROOT / "tests" / "fixtures" / "changelog.rss",
            ROOT / "tests" / "fixtures" / "previous_latest.md",
            ROOT / ".github" / "workflows" / "test.yml",
            ROOT / ".gitignore",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, path)
            self.assertNotIn("\u2013", text, path)


if __name__ == "__main__":
    unittest.main()
