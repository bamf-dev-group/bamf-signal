# BAMF Signal

A plain-text feed of what changed in HighLevel, written so an AI assistant inside a HighLevel
account can read it and turn it into account-specific recommendations.

One file per sweep in `digests/`, named `YYYY-MM-DD.md`. `digests/latest.md` always mirrors the
most recent one, so the URL an automation points at never changes.

Every entry is sourced from HighLevel's own changelog. Anything from a third party is labeled
unofficial and is never treated as a source of record.

## How to use it

Point a scheduled AI prompt at the raw URL:

```
https://raw.githubusercontent.com/justinbamfdev/bamf-signal/main/digests/latest.md
```

No credential, no connector, no expiry. It returns plain text to anything that can fetch a URL.

## Automated refresh

`.github/workflows/digest-refresh.yml` rewrites `digests/latest.md` on weekdays at 11:40 UTC
(04:40 MST, 05:40 during daylight saving time) and on manual `workflow_dispatch`, which has a
`dry_run` input that builds the file and shows the diff without committing. It reads HighLevel's
public changelog feed, which holds only the newest 10 entries. When those 10 do not reach back to
the previous digest's newest entry, it also pages the public `getEntries` endpoint behind the
changelog page (no credential), merges the two sources and drops duplicates by link or guid. If
`getEntries` fails, it uses the feed alone and prints the `Coverage gap:` line. The layout is the
same as the hand-curated digest: title, `Fetched:`, `Covers entries dated`, a computed `Coverage gap:` line, tier counts, HIGH, MEDIUM and LOW
sections, an UNTIERED section holding the automated entries, and the `Not shipped` section, which
is carried forward unchanged from the previous file.

It commits with the built-in `GITHUB_TOKEN` even when nothing is new, because the `Fetched:` line
changes. If the newest entry is more than 2 weekdays old, the title keeps the newest entry date
instead of today, a `STALE:` line is added, and the job fails. Any failure opens or updates an
issue titled "digest-refresh failure", which is closed on the next good run.

Run the parser tests locally with `python3 -m unittest discover -s tests`. The same tests run on
every pull request via `.github/workflows/test.yml`.

## What the tiers mean

- **HIGH** - changes a build pattern, replaces or deprecates something, or is a new capability
  worth selling or teaching.
- **MEDIUM** - a real improvement to something you already use.
- **LOW** - cosmetic, a bug fix, or a narrow edge case.

An item earns a tier only if it changes something live in a real account. Impressive but
inapplicable does not qualify, and a new tool only counts if it replaces one already in use.

---

Published by BAMF Development Group LLC. Free to read, free to point your own automation at.
