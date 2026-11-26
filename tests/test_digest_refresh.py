import datetime as dt
import pathlib
import sys
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


class EnrichTests(unittest.TestCase):
    def test_fills_only_empty_summaries(self):
        entries = dr.parse_rss(FIXTURE)
        payload = {
            "entries": [
                {"title": "No summary entry", "description": "<p>From the API.</p>"},
                {"title": "Older & simpler update", "description": "Should not replace"},
            ]
        }
        dr.enrich(entries, payload)
        self.assertEqual(entries[1]["summary"], "From the API.")
        self.assertEqual(entries[2]["summary"], "Plain older summary.")

    def test_unknown_payload_is_harmless(self):
        entries = dr.parse_rss(FIXTURE)
        dr.enrich(entries, {"unexpected": 1})
        self.assertEqual(entries[1]["summary"], "")


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.out = dr.render(dr.parse_rss(FIXTURE), NOW)
        self.lines = self.out.splitlines()

    def test_header_and_fetched_lines(self):
        self.assertEqual(self.lines[0], "# HighLevel digest, 2026-11-20")
        self.assertIn("Fetched: 2026-11-20T11:40:05Z", self.lines)

    def test_coverage_line(self):
        cov = [l for l in self.lines if l.startswith("Coverage:")][0]
        self.assertIn("3 entries dated 2026-11-17 through 2026-11-19", cov)

    def test_entries_have_date_title_link_summary(self):
        self.assertIn("## 2026-11-19: Newest feature - now live", self.lines)
        self.assertIn("Link: https://ideas.gohighlevel.com/changelog/newest-feature", self.lines)
        self.assertIn("First line. Second point", self.lines)
        self.assertLess(self.out.index("2026-11-19:"), self.out.index("2026-11-17:"))

    def test_no_tiers_or_dashes(self):
        for tier in ("## HIGH", "## MEDIUM", "## LOW"):
            self.assertNotIn(tier, self.out)
        self.assertNotIn("\u2014", self.out)
        self.assertNotIn("\u2013", self.out)


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
    def test_no_em_or_en_dashes_in_repo_files(self):
        paths = [
            ROOT / "README.md",
            ROOT / ".github" / "workflows" / "digest-refresh.yml",
            ROOT / "scripts" / "digest_refresh.py",
            ROOT / "tests" / "test_digest_refresh.py",
            ROOT / "tests" / "fixtures" / "changelog.rss",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, path)
            self.assertNotIn("\u2013", text, path)


if __name__ == "__main__":
    unittest.main()
