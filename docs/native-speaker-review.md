# Native-Speaker Review

This document defines how Swahili commentary is reviewed before a quality number is published. It is deliberately a human sign-off process: automated checks catch groundedness and formatting problems, but they cannot certify natural Swahili football register.

## Scope

Review the **caption text**, not the English gloss alone. The gloss exists so a non-Swahili reviewer can follow the claim, but the rating must come from a fluent Swahili speaker.

Review at least:

- 1 goal call from each perspective (home / away / neutral)
- 1 red-card or big-chance moment
- 1 momentum or stat-led analyst card
- 1 late-game call
- 1 fallback/template line

Aim for **30 reviewed lines** before quoting an average. Do not publish a score from fewer than 30 lines.

## Rubric (1–5 each)

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Fluency | Hard to follow; grammar or agreement errors | Understandable but stilted | Natural spoken Swahili |
| Idiom / register | Literal translation; no football register | Some football vocabulary | Sounds like live Swahili radio commentary |
| Faithfulness | Adds or changes a fact | Mostly faithful, minor ambiguity | Every claim matches the moment and evidence |

Also record any **blocking** issue separately:

- wrong player, team, minute, score, or metric
- missing English gloss
- fabricated fact
- unsafe or abusive language
- number written in a way the speech voice will mispronounce

A line with a blocking issue cannot be approved even if its style score is high.

## Reviewer workflow

1. Open `/review` and unlock it with the reviewer key.
2. For each Swahili line, read the line and its English gloss.
3. Enter the three scores, an optional note, and a corrected version when needed.
4. Submit. The review is stored with the reviewer name and timestamp.
5. A second reviewer must confirm any line that is approved with a correction. The dashboard records `requires_second_review` on edited lines and the export holds them out until that confirmation is recorded; the current demo does not automate the second-review handoff.
6. Export the signed-off set before quoting a score:

```bash
python scripts/export_swahili_review.py --min-lines 30
```

The export refuses to produce a summary until 30 distinct lines have a complete review and a named sign-off.

## What counts as approved

A line is **approved** only when:

- all three scores are present;
- no blocking issue is open;
- the reviewer name is present;
- the English gloss is present; and
- a second reviewer has confirmed any edited line.

Until then the status is **pending**, and the README must not quote a rating.

## Data handling

- Do not put reviewer keys or personal data in the repository.
- Review notes may contain Swahili text but no secrets.
- The review queue is served by the backend; approved corrections use the same Cosmos-backed corrections container as viewer feedback.
- If Cosmos is unavailable, the app keeps an in-memory mirror and the review still works for the current session. Persist the export before ending the session.
