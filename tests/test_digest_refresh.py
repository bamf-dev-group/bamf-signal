import datetime as dt
import os
import pathlib
import sys
import tempfile
import unittest

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
