# World Cup Data Triangulation & Verification Plan

> **For Hermes:** Execute this plan task-by-task using `subagent-driven-development` after Boss approves.

**Goal:** Ensure every match score, scorer, minute mark, and penalty result in the WC daily briefing is verified against **2+ independent trusted sources** before publishing — eliminating the recurring hallucinated-data bugs (fabricated scorers, reversed winners, wrong minute marks).

**Current Architecture:**
- `world-cup-data.json` — single source of truth (LLM-authored)
- `generate-briefing.py` — reads JSON → generates HTML (deterministic, no LLM)
- `validate-briefing.py` — cross-refs HTML scores vs JSON (can't catch wrong JSON)
- `verify-source.py` — fetches Wikipedia, checks scores only, R32-only
- Cron job `70a4279f9fc1` runs the daily flow (06:00 SGT)

**Gaps:**
1. verify-source.py only checks scores, NOT scorers/minute marks
2. verify-source.py only handles R32 (soon obsolete when R16 starts)
3. Single source (Wikipedia) only — no triangulation
4. Cron prompt doesn't enforce running verify-source.py as a gate before push

---

## Task 1: Extend verify-source.py to check scorers & minute marks

**Objective:** Add scorer name + minute verification alongside score checking, so fabricated scorers (like the France-Sweden bug) are caught.

**Files:**
- Modify: `/home/dennis/pages-repo/verify-source.py`

**Details:**

Add a new function `parse_scorers(section_text)` that extracts scorer data from Wikipedia's match report format:

```
France 3–0 Sweden
Mbappé 45', 74', Barcola 53' | Nilsson 67'
```

The function should return a dict per match: `{home: [{name, minute}], away: [{name, minute}]}`

Add a new cross-reference pass after score checking:
- For each completed match in JSON, parse the Wikipedia section's scorer list
- Compare each JSON `scorers` field entry against Wikipedia's list
- Accept minor formatting differences ("Mbappé 45', 74'" vs "Mbappé 45', Mbappé 74'")
- Flag missing or extra scorers, wrong minute marks (within ±2 min tolerance)
- Exit 1 on any mismatch with clear diagnostics

**Verification:**
```bash
python3 /home/dennis/pages-repo/verify-source.py
# Expected: ✅ All completed matches verified against Wikipedia (scores + scorers)
# If France 3-0 Sweden was fabricated, expect: ❌ Scorer mismatch for Mbappé
```

---

## Task 2: Add second verification source (ESPN/FIFA)

**Objective:** Add cross-reference against at least one additional independent source. Wikipedia can be slow to update for very recent matches (last 4 hours). Use ESPN's match centre as second source.

**Files:**
- Create: `/home/dennis/pages-repo/verify-source-espn.py`
- Modify: `/home/dennis/pages-repo/verify-source.py` (add option to accept a secondary source)

**Approach:**

Use `urllib` to fetch ESPN's World Cup scoreboard page and parse match results. Alternative: scrape a simpler aggregator.

Keep this as a separate script that runs independently:
```bash
python3 /home/dennis/pages-repo/verify-source-espn.py
# Exit 0 = matches ESPN, 1 = mismatch, 2 = fetch error
```

Or simpler: extend `verify-source.py` to accept `--secondary` flag that fetches from a different source and requires both to agree.

**Source candidates:**
- `https://www.espn.com/soccer/scoreboard/_/league/fifa.world/date/YYYYMMDD`
- `https://api.fifa.com/api/v3/calendar/matches?competitionCode=WC&seasonYear=2026`
- Or use LiveScore.com browser-fetch for JS-rendered data

**Acceptance:** Both Wikipedia AND secondary source must agree on the score. If one disagrees or is unreachable, flag for manual review but don't block (network issues shouldn't block push).

---

## Task 3: Add penalty-shootout verification

**Objective:** Catch the "winner reversed" bugs (Belgium vs Senegal, Germany vs Paraguay) where the penalty winner was reported incorrectly.

**Files:**
- Modify: `/home/dennis/pages-repo/verify-source.py`

**Details:**
- For FT-pens matches, Wikipedia shows `(a.e.t.)` marker and separate penalty result
- Parse the penalty score line (e.g. "3–4 on penalties")
- Cross-reference `penalty_winner` in JSON against Wikipedia's penalty result
- Also check: the final score after penalties (home team may be different from winner)

**Scoring logic:**
- FT-pens score is the 120min score (e.g. Germany 1-1 Paraguay)
- Penalty score is separate (e.g. 3-4)
- Winner is the team that wins the penalty shootout

**Verification:**
```bash
python3 /home/dennis/pages-repo/verify-source.py
# Should catch: Belgium 3-2 Senegal with penalty_winner: Belgium ✅
# Should catch: Belgium 0-2 Senegal ❌ (winner reversed)
```

---

## Task 4: Make the verifier phase-aware (R32 → R16 → QF → SF → Final)

**Objective:** As the tournament progresses, `verify-source.py` must adapt to whichever round is current.

**Files:**
- Modify: `/home/dennis/pages-repo/verify-source.py`

**Approach:**

Replace the hardcoded `"Round of 32 Main article"` anchor with a phase-detection function:

```python
PHASE_ANCHORS = {
    "Round of 32": "Round of 32 Main article",
    "Round of 16": "Round of 16 Main article",
    "Quarter-finals": "Quarter-finals Main article",
    "Semi-finals": "Semi-finals Main article",
    "Third place play-off": "Third place play-off Main article",
    "Final": "Final Main article",
}
```

Auto-detect which phases exist in the Wikipedia page and verify matches in whichever round(s) the JSON has completed matches for.

Also support verifying UPCOMING matches (check that the scheduled date/time/teams match Wikipedia).

---

## Task 5: Add scorer-source receipt tracking to cron prompt (prevention, not just detection)

**Objective:** Prevent LLM from fabricating scorer data by requiring explicit source receipts during research.

**Files:**
- Modify: Cron job `70a4279f9fc1` prompt
- Possibly: `/home/dennis/pages-repo/world-cup-data.json` (add `sources` field)

**Details:**

Add a `sources` field to each match in the JSON:
```json
{
  "id": 77,
  "...": "...",
  "sources": {
    "score": ["https://fifa.com/...", "https://en.wikipedia.org/..."],
    "scorers": ["https://espn.com/..."],
    "verified_at": "2026-07-03T06:15:00+08:00"
  }
}
```

Add a HARD RULE block at the TOP of the cron prompt (after the date gate):

```
====================================================================
HARD RULE — TRIANGULATION GATE
====================================================================

For EVERY completed match you report:

1. FIND the result on at least 2 INDEPENDENT sources (choose from:
   Wikipedia, FIFA.com, ESPN, AP News, The Guardian, BBC Sport).
   The two sources must AGREE on winner, score, and all goal scorers.

2. RECORD the source URLs in the match's `sources` field.

3. If a match finished within the last 4 hours and Wikipedia hasn't
   updated yet, use ESPN or The Guardian's live blog as your primary
   source, but DO NOT write the score until you have 2 independent
   confirmations.

4. For PENALTY SHOOTOUTS: record BOTH the 120min score AND the
   penalty winner separately. Verify both agree across sources.

5. For SCORER + MINUTE: verify each scorer name AND minute mark.
   A scorer at a wrong minute is still an error even if the
   name exists. Tolerance: ±2 minutes.

6. Before writing ANY value to world-cup-data.json, you must have
   found it in at least 2 sources. If you cannot find 2 sources
   for any data point, set the value to null and flag it.

7. RUN the verification GATE before git push:
   python3 /home/dennis/pages-repo/verify-source.py
   Exit 0 = push OK. Exit 1 = BLOCKED — fix data, retry.
   Exit 2/3 = source issue — note it, push at your discretion.

8. DO NOT substitute "the validator didn't complain" for actual
   verification. The validator cross-refs JSON against external
   sources. If you wrote wrong data into the JSON, the validator
   catches it — but only if the external source has the right data.
====================================================================
```

---

## Task 6: Update cron prompt to run verifier as pre-publish gate

**Objective:** Make verify-source.py run as part of the cron pipeline, blocking git push on mismatch.

**Files:**
- Modify: Cron job `70a4279f9fc1` prompt (insert pipeline steps)

**Cron pipeline (new sequence):**

```
CRON PIPELINE (execute in order):
1. DATE GATE — if today >= 2026-07-20, [SILENT] exit
2. RESEARCH — find latest results from 2+ sources each
3. UPDATE DATA — edit world-cup-data.json with verified values
4. GENERATE — python3 generate-briefing.py
5. VALIDATE (internal) — python3 validate-briefing.py  (check HTML vs JSON)
6. VALIDATE (external) — python3 verify-source.py       (check JSON vs Wikipedia)
7. If step 6 passes → git commit + push
8. If step 6 fails → DO NOT push. Fix data and retry from step 3.
9. DELIVER — HTML URL to user
```

---

## Task 7: Test updated verifier with known-past failures

**Objective:** Regression-test verify-source.py against the known errors that shipped in previous cron runs to confirm the new checks catch them.

**Test cases to create:**
- `Belgium 0-2 Senegal` (winner reversed — should now be caught)
- `France 3-0 Sweden` with fabricated scorers (should now be caught)
- `Mexico 2-0 Ecuador` with wrong minute marks (should now be caught)
- `Germany 1-1 Paraguay` with reversed penalty winner (should now be caught)

Create as a test script or manually run with modified JSON.

---

## Files Summary

| File | Action |
|------|--------|
| `/home/dennis/pages-repo/verify-source.py` | Modify — add scorer/minute verification, penalty verification, phase-awareness |
| `/home/dennis/pages-repo/verify-source-espn.py` | Create — secondary source cross-reference (optional, can merge into verify-source.py) |
| `/home/dennis/pages-repo/world-cup-data.json` | Modify — add `sources` field to each match (optional) |
| Cron job `70a4279f9fc1` | Update prompt — add HARD RULE + pipeline steps |
| Cron job `c2fb7d17504d` | Update prompt — same HARD RULE for night-before alerts |

## Risks & Tradeoffs

1. **Wikipedia is user-edited** — theoretically wrong. Practically, it's the most reliable free source for WC results, updated within minutes. The secondary source (ESPN/AP) mitigates this.
2. **Recent matches (< 4h old)** — Wikipedia may not be updated yet. Script must handle gracefully (exit 2, don't block).
3. **Phase changes** — When R16 starts on Jul 4, verify-source.py needs to anchor on "Round of 16 Main article". Must be ready before then.
4. **Script run time** — Fetching and parsing Wikipedia + ESPN takes ~5-10s. Acceptable for a 06:00 cron.
5. **Cron toolsets** — verify-source.py uses `urllib` (stdlib). No additional deps needed.

## Verification

After all tasks:
```bash
# Full pipeline test
cd /home/dennis/pages-repo
python3 generate-briefing.py
python3 validate-briefing.py       # exit 0
python3 verify-source.py           # exit 0 (scores + scorers match Wikipedia)
# Then push
```

```bash
# Regression test with known-bad data
# Temporarily edit JSON with Belgium 0-2 Senegal
python3 verify-source.py           # exit 1 — "M82: Belgium 0-2 Senegal — WIKIPEDIA SAYS 3-2 a.e.t."
```
