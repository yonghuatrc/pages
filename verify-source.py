#!/usr/bin/env python3
"""
verify-source.py — Deterministic source gate for the World Cup briefing cron.

Catches the "string-existence self-check" trap (html-content-verification
pitfall 4.6): the cron's previous validator only confirmed the LLM's own
JSON strings appeared in the HTML. This script fetches an EXTERNAL source
(Wikipedia's 2026 FIFA World Cup page) and cross-references the JSON's
match results against it. If any completed match disagrees with
Wikipedia, exits 1 (block push) with a diagnostic. Otherwise exits 0.

Why Wikipedia (not FIFA.com)?  No public free API for 2026 WC results.
Wikipedia is updated within minutes of FT and is the most reliable free
source.

How it parses Wikipedia:
  Anchors on the "Round of 32 Main article" subsection, which contains
  detailed match reports in the format:
    <date> <time> <TeamA> <H-A> [ (a.e.t.) ] <TeamB> <scorers> [ Report N ]
  where <H-A> is the final score (H = home, A = away).

Usage:
  python3 verify-source.py              # uses default JSON path
  python3 verify-source.py path/to/json # explicit path

Exit codes:
  0 = JSON matches Wikipedia (push OK)
  1 = JSON disagrees with Wikipedia (block push, see stderr)
  2 = Could not fetch Wikipedia (infrastructure issue, not data issue)
  3 = Wikipedia page structure changed (update this script)
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_JSON = Path(__file__).parent / "world-cup-data.json"
WIKI_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup"
USER_AGENT = "Mozilla/5.0 (compatible; hermes-cron/1.0)"


def fetch_wiki():
    """Fetch the 2026 WC Wikipedia page and strip to plain text."""
    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text


def extract_r32_section(wiki_text):
    """
    Return the text of the R32 detailed match reports section.

    Bounded by "Round of 32 Main article" (start) and either
    "Round of 16 Main article" (end) or the next major section.
    """
    start = wiki_text.find("Round of 32 Main article")
    if start == -1:
        return None
    end = wiki_text.find("Round of 16 Main article", start + 1)
    if end == -1:
        end = start + 15000
    return wiki_text[start:end]


def parse_match_reports(section_text):
    """
    Parse every "TeamA H-A TeamB" detailed match report.

    Returns a list of dicts: {home, away, h_goals, a_goals, is_aet}
    """
    # Normalise en-dash to ASCII hyphen for easier regex
    norm = section_text.replace("\u2013", "-").replace("\u2014", "-")

    # Team name: 1-4 capitalised words (handles "Ivory Coast", "DR Congo",
    # "Bosnia & Herzegovina", "Cape Verde" etc.)
    # Allow ampersand, hyphen, period, apostrophe within words
    # Use a word-class that's safe across all unicode ranges
    word = r"[A-Z][A-Za-z\u00c0-\u017f'\.\-]+"
    team = rf"{word}(?:\s+(?:[&\-]|{word}))*"

    # Score: H-A
    score = r"(\d+)\s*-\s*(\d+)"

    # Optional a.e.t. marker
    aet = r"(?:\s*\(\s*a\.e\.t\.\s*\)\s*)?"

    # Lookahead: after TeamB, the next thing is either:
    #   - "[ Report N ]" (start of scorer section)
    #   - "Penalties" (start of penalty section)
    #   - a capital letter (start of scorer name)
    lookahead = r"(?=\s+\[|\s+Penalties|\s+[A-Z])"

    pat = rf"({team})\s+{score}{aet}\s+({team}){lookahead}"

    results = []
    for m in re.finditer(pat, norm):
        home, h, a, away = m.group(1).strip(), m.group(2), m.group(3), m.group(4).strip()
        is_aet = "a.e.t." in m.group(0)

        # Filter false positives:
        # - Penalty-shooter lists look like "Penalties Havertz Kimmich 3-4 Maurício"
        #   The "home" team would be "Penalties" — filter by checking
        #   that home/away don't start with a non-team word.
        non_team = {
            "Penalties", "Statistics", "Goalscorers", "See also",
            "Award", "Awards", "Source", "Referee",
        }
        if home in non_team or away in non_team:
            continue
        # Penalty score entries like "Tah 3-4 Maurício" — away starts with a single word
        # that's not a team. Filter by requiring home to be 2+ chars AND no digit
        if any(c.isdigit() for c in home) or any(c.isdigit() for c in away):
            continue
        # Heuristic: a team name should have at most 4 words
        if len(home.split()) > 4 or len(away.split()) > 4:
            continue

        results.append({
            "home": home,
            "away": away,
            "h_goals": int(h),
            "a_goals": int(a),
            "is_aet": is_aet,
        })

    # Dedupe
    seen = set()
    deduped = []
    for r in results:
        key = (r["home"], r["away"], r["h_goals"], r["a_goals"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def team_matches(a, b):
    """Loose team-name match (handles DR Congo, Côte d'Ivoire, etc.)."""
    a_norm = re.sub(r"[^a-z]", "", a.lower())
    b_norm = re.sub(r"[^a-z]", "", b.lower())
    if a_norm == b_norm:
        return True
    alternates = {
        "ivorycoast": "cotedivoire",
        "cotedivoire": "ivorycoast",
        "bosniaandherzegovina": "bosnia",
        "bosnia": "bosniaandherzegovina",
        "drcongo": "congo",
        "congo": "drcongo",
        "capeverde": "caboverde",
        "caboverde": "capeverde",
    }
    if alternates.get(a_norm) == b_norm or alternates.get(b_norm) == a_norm:
        return True
    # Substring match (must be at least 5 chars to avoid false matches)
    if len(a_norm) >= 5 and len(b_norm) >= 5:
        if a_norm in b_norm or b_norm in a_norm:
            return True
    return False


def main():
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON
    if not json_path.exists():
        print(f"\u274C  {json_path} not found", file=sys.stderr)
        return 1

    with open(json_path) as f:
        data = json.load(f)

    print("Fetching Wikipedia source...")
    try:
        wiki_text = fetch_wiki()
    except Exception as e:
        print(f"\u274C  Could not fetch Wikipedia: {e}", file=sys.stderr)
        return 2

    section = extract_r32_section(wiki_text)
    if section is None:
        print("\u274C  Could not find 'Round of 32 Main article' section in Wikipedia", file=sys.stderr)
        print("    The page structure may have changed \u2014 update this script.", file=sys.stderr)
        return 3

    matches = parse_match_reports(section)
    if not matches:
        print("\u274C  Parsed 0 match reports from R32 section", file=sys.stderr)
        print("    The page structure may have changed \u2014 update this script.", file=sys.stderr)
        return 3

    print(f"   Found {len(matches)} unique R32 match reports from Wikipedia")

    # Cross-reference each completed match in our JSON
    errors = []
    json_matches = [m for m in data["matches"] if m["status"] in ("FT", "FT-pens")]
    print(f"   Cross-referencing {len(json_matches)} completed matches in JSON...")

    for jm in json_matches:
        h_name = jm["home"]["name"]
        a_name = jm["away"]["name"]
        h_goals = jm["home"]["goals"]
        a_goals = jm["away"]["goals"]

        # Find matching wiki entry
        match = None
        for wm in matches:
            if (team_matches(wm["home"], h_name) and team_matches(wm["away"], a_name)) or \
               (team_matches(wm["home"], a_name) and team_matches(wm["away"], h_name)):
                match = wm
                break

        if not match:
            errors.append(
                f"M{jm['id']}: {h_name} {h_goals}-{a_goals} {a_name} \u2014 "
                f"NOT FOUND in Wikipedia R32"
            )
            continue

        # Check score (either direction, since home/away can swap in bracket view)
        if not (
            (match["h_goals"] == h_goals and match["a_goals"] == a_goals) or
            (match["h_goals"] == a_goals and match["a_goals"] == h_goals)
        ):
            errors.append(
                f"M{jm['id']}: {h_name} {h_goals}-{a_goals} {a_name} \u2014 "
                f"WIKIPEDIA SAYS {match['h_goals']}-{match['a_goals']} "
                f"({match['home']} v {match['away']})"
            )

    if errors:
        print()
        print("\u274C  DATA MISMATCH \u2014 push blocked", file=sys.stderr)
        print()
        for e in errors:
            print(f"  \u2022 {e}", file=sys.stderr)
        print()
        print(
            "Fix world-cup-data.json, re-run the generator, and re-run this gate.",
            file=sys.stderr,
        )
        return 1

    print()
    print(f"\u2705  All {len(json_matches)} completed matches verified against Wikipedia")
    print(f"   Source: {WIKI_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
