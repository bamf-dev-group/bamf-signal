# HighLevel digest, 2026-08-26

Covers entries dated Aug 23 through Aug 26 2026. Source: HighLevel's official changelog at
ideas.gohighlevel.com/changelog.

Coverage gap: Aug 19 through Aug 22 was not retrieved in this sweep and is not reported here.

5 HIGH, 4 MEDIUM, 2 LOW.

---

## HIGH

### Anthropic and Google models now run in the AI Agent workflow action
The AI Agent workflow action was OpenAI only. It now also runs Claude Opus 5, Sonnet 5, and
Haiku 4.5, plus Gemini 3.6 Flash and 3.1 Pro Preview, with per-model reasoning-effort control.
**What to do:** if any workflow of yours routes out to an external AI service just to use a
specific model, that hop can now happen inside the workflow.
Date unconfirmed in this sweep.

### Numeric and monetary custom fields became reporting metrics
Custom fields on Contacts and Opportunities can now be aggregated with Sum, Min, Max, and
Average in dashboards and custom reports. New fields appear in the metric picker automatically.
**What to do:** any number you currently export to a spreadsheet to total up can probably become
a dashboard widget instead. Check your monetary custom fields first.
Aug 23 2026.

### Chat widget compliance notice and consent settings split apart
The single all-in-one compliance toggle is replaced by a compliance notice that shows without
requiring visitor action, plus a separate consent checkbox with wording you control, for
explicit SMS or email opt-in.
**What to do:** if you send SMS, this is the cleanest place to capture written consent. Set the
checkbox wording deliberately rather than leaving the default.
Aug 25 2026.

### One calendar can offer up to three meeting durations
Bookers choose their meeting length inside a single calendar instead of you maintaining a
separate calendar per duration.
**What to do:** if you run separate calendars for a short intro call and a longer strategy call,
those can collapse into one.
Aug 25 2026.

### Bulk workflow triggering for Companies and custom objects
Select multiple Company or custom-object records from a list view and push them all into a
workflow at once, with progress tracked under Bulk Actions.
**What to do:** custom objects that were storage-only can now drive automation without building
a record-by-record trigger.
Aug 26 2026.

## MEDIUM

### Zero-dollar checkout in Forms and Surveys
Forms and surveys skip card collection when the order total is zero. Useful for any free offer
that currently asks for a card it does not need.
Aug 24 2026.

### Chat widget pulls from Brand Boards
The widget's Styles panel reads brand colors and fonts from the location's Brand Board instead
of needing manual entry.
Aug 25 2026.

### Marketplace app approval controls
Agencies can restrict sub-account access to approved apps only, through one toggle.
Aug 26 2026.

### Calendar guest enhancements
Guest records can collect phone numbers, and new guest contacts inherit the primary contact's
timezone, which removes a common wrong-timezone booking failure.
Aug 26 2026.

## LOW

### Request contact info from WhatsApp username users
A share-contact-info button converts anonymous WhatsApp username users into contactable records.
Aug 25 2026.

### WhatsApp template builder validates variables inline
Invalid variable placeholders are caught before save instead of on rejection.
Aug 25 2026.

---

## Not shipped, in case you heard otherwise

**Project management.** HighLevel has not shipped a projects or project-management product, and
there is no published ship date. The idea-board request "Project/Task Organizer Like Asana" has
been open since Jan 2019, sits at Under review with roughly 1.6k votes, and the only official
response is a pinned comment from May 2025 saying HighLevel is exploring improvements to Tasks.
The most recent related shipment is Task Manager V2 on the mobile app, June 11 2026.
