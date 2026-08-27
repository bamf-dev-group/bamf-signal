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

## What the tiers mean

- **HIGH** - changes a build pattern, replaces or deprecates something, or is a new capability
  worth selling or teaching.
- **MEDIUM** - a real improvement to something you already use.
- **LOW** - cosmetic, a bug fix, or a narrow edge case.

An item earns a tier only if it changes something live in a real account. Impressive but
inapplicable does not qualify, and a new tool only counts if it replaces one already in use.

---

Published by BAMF Development Group LLC. Free to read, free to point your own automation at.
