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

# Secondary source: ESPN API. Public free endpoint, no auth needed.
# Returns JSON with scoreboard data including completed R32 matches.
ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"


def fetch_wiki():
    """Fetch the 2026 WC Wikipedia page and strip to plain text."""
    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text


PHASE_ANCHORS = {
    "Round of 32": "Round of 32 Main article",
    "Round of 16": "Round of 16 Main article",
    "Quarter-finals": "Quarter-finals Main article",
    "Semi-finals": "Semi-finals Main article",
    "Third place play-off": "Third place play-off Main article",
    "Final": "Final Main article",
}


def extract_phase_section(wiki_text, phase=None):
    """
    Return the text of a phase's detailed match reports section.

    Bounded by the phase's "Main article" anchor (start) and the next phase's
    anchor (end). If phase is None, auto-detect the first phase with matches.

    Returns (section_text, phase_name) or (None, None) if no phases found.
    """
    # Build ordered list of phases present in the wiki text
    found_phases = []
    for phase_name, anchor in PHASE_ANCHORS.items():
        idx = wiki_text.find(anchor)
        if idx >= 0:
            found_phases.append((phase_name, anchor, idx))
    # Sort by position in text (chronological order)
    found_phases.sort(key=lambda x: x[2])
    if not found_phases:
        return None, None
    # If a specific phase requested, find it; else use the first
    if phase:
        for phase_name, anchor, start in found_phases:
            if phase_name == phase:
                # End = next phase's anchor position
                idx_in_list = found_phases.index((phase_name, anchor, start))
                if idx_in_list + 1 < len(found_phases):
                    end = found_phases[idx_in_list + 1][2]
                else:
                    end = start + 15000
                return wiki_text[start:end], phase_name
        return None, None
    # Default: use the first phase
    phase_name, anchor, start = found_phases[0]
    if len(found_phases) > 1:
        end = found_phases[1][2]
    else:
        end = start + 15000
    return wiki_text[start:end], phase_name


def extract_r32_section(wiki_text):
    """Legacy wrapper — uses extract_phase_section with no specific phase."""
    section, _ = extract_phase_section(wiki_text)
    return section


def parse_match_reports(section_text):
    """
    Parse every "TeamA H-A TeamB" detailed match report.

    Returns a list of dicts:
        {home, away, h_goals, a_goals, is_aet,
         home_scorers: [{name, minute}, ...],
         away_scorers: [{name, minute}, ...],
         pens_score: (h, a) or None,
         pens_winner: home|away or None}
    """
    # Normalise en-dash to ASCII hyphen for easier regex
    norm = section_text.replace("\u2013", "-").replace("\u2014", "-")

    # Team name: 1-4 capitalised words (handles "Ivory Coast", "DR Congo",
    # "Bosnia & Herzegovina", "Cape Verde" etc.)
    # Team name: 1-4 words. Capitalized words always; lowercase connectors
    # "and", "of", "the" allowed between them (handles "Bosnia and Herzegovina",
    # "Ivory Coast", "DR Congo", "Cape Verde", "São Tomé and Príncipe").
    word = r"[A-Z][A-Za-z\u00c0-\u017f'\.\-]+"
    connector = r"(?:and|of|the|de|du|la|le)"
    team = rf"{word}(?:\s+(?:[&\-]|{word}|{connector}))*"

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

        # Filter false positives
        non_team = {
            "Penalties", "Statistics", "Goalscorers", "See also",
            "Award", "Awards", "Source", "Referee",
        }
        if home in non_team or away in non_team:
            continue
        if any(c.isdigit() for c in home) or any(c.isdigit() for c in away):
            continue
        if len(home.split()) > 4 or len(away.split()) > 4:
            continue

        # Extract scorer block: home scorers + [Report N] + away scorers
        # Format: "Home_Scorers [ Report N ] Away_Scorers Stadium..."
        # Boundaries: end is "Stadium" or "Attendance" or "Source:" or "Penalties"
        #             (we stop BEFORE the penalty list for FT-pens matches)
        start_pos = m.end()
        # Walk forward finding each Report marker and the away scorers after it
        boundary = None
        for marker in [r"\s+Source:\s*FIFA",
                       r"\s+[A-Z][a-z]+\s+Stadium",
                       r"\s+Attendance"]:
            mm = re.search(marker, norm[start_pos:])
            if mm:
                pos = start_pos + mm.start()
                if boundary is None or pos < boundary:
                    boundary = pos
        if boundary is None:
            scorer_block = norm[start_pos:start_pos + 500]
        else:
            scorer_block = norm[start_pos:boundary]

        home_scorers, away_scorers, pens_score, pens_winner = parse_scorers_and_pens(
            scorer_block, is_aet
        )

        results.append({
            "home": home,
            "away": away,
            "h_goals": int(h),
            "a_goals": int(a),
            "is_aet": is_aet,
            "home_scorers": home_scorers,
            "away_scorers": away_scorers,
            "pens_score": pens_score,
            "pens_winner": pens_winner,
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


def parse_scorers_and_pens(scorer_block, is_aet):
    """
    Parse scorer names + minute marks from a match report scorer block.

    Format examples (before [Report N]):
        "Mbappé 45' , 74' Barcola 53'"
        "Havertz 54' (pen.)" — note penalty marker on minute
    After [Report N]:
        "Mbaye 90+5'"
        "Diarra 25' I. Sarr 51'"
        "Perišić 53'"

    Returns: (home_scorers, away_scorers, pens_score, pens_winner)
      home_scorers = list of {"name": str, "minute": int, "pen": bool}
      away_scorers = same
      pens_score = (home_pen_goals, away_pen_goals) or None
      pens_winner = "home" | "away" | None
    """
    # Scorer pattern: Name 45' (optional (pen.)) — comma-separated minutes
    # Examples: "Mbappé 45'", "Mbappé 45', 74'", "Havertz 54' (pen.)"
    # Handle names with diacritics, apostrophes, hyphens, periods
    name_pat = r"[A-Z][\w\u00c0-\u017f'\.\-]+(?:\s+[A-Z][\w\u00c0-\u017f'\.\-]+)*"
    minute_pat = r"\s*(\d+)\s*(\+\s*\d+)?\s*'(?:\s*\(\s*pen\.?\s*\))?"
    scorer_pat = rf"({name_pat}){minute_pat}"

    scorers = []
    for sm in re.finditer(scorer_pat, scorer_block):
        name = sm.group(1).strip()
        minute = int(sm.group(2))
        if sm.group(3):  # "+NN" present
            minute_str = sm.group(2) + sm.group(3).replace(" ", "").replace("+", "+")
            # Keep base minute for comparison; full string available if needed
        pen = "pen" in sm.group(0).lower()
        scorers.append({
            "name": name,
            "minute": minute,
            "pen": pen,
            "raw": sm.group(0).strip(),
        })

    # Check for penalty shootout result at end: "Tah 3-4 Maurício" pattern
    pens_score = None
    pens_winner = None
    pens_match = re.search(r"\b(\d+)\s*-\s*(\d+)\s*$", scorer_block.rstrip().rstrip("."))
    # Better: look for the pattern after "Penalties" or last digit-only pair
    if is_aet:
        # Look for the penalty score pattern. Format:
        # "Names Names Names H-A Names Names" or just "H-A" within the Penalties section.
        # The H-A is preceded by at least one name and followed by names (or end).
        # Find the last "N-N" in the Penalties section.
        pen_idx = scorer_block.find("Penalties")
        if pen_idx >= 0:
            pen_section = scorer_block[pen_idx:]
            # Find last "N-N" in the Penalties section (the actual shootout score)
            # Avoid matching minute marks like "90+1'"
            # Match a digit pair separated by hyphen, surrounded by name-like context
            scores = re.findall(r"(?:^|\s)(\d+)\s*-\s*(\d+)(?:\s|$)", pen_section)
            # Filter out numbers that look like stoppage times (e.g. "90-5" doesn't apply,
            # but "5-4" in "Summerville 2-3 El Aynaoui" is a penalty score)
            if scores:
                # Take the LAST score (the actual shootout result)
                last = scores[-1]
                h_pens = int(last[0])
                a_pens = int(last[1])
                pens_score = (h_pens, a_pens)
                pens_winner = "home" if h_pens > a_pens else "away" if a_pens > h_pens else None

    # Split scorers by "[ Report N ]" — everything before is home, after is away.
    # In the scorer_block passed in, the [Report N] marker is the boundary.
    report_split = re.search(r"\[\s*Report\s+\d+\s*\]", scorer_block)
    if report_split:
        home_block = scorer_block[:report_split.start()]
        away_block = scorer_block[report_split.end():]
    else:
        # No [Report N] — assume all scorers are home (no away goal section)
        home_block = scorer_block
        away_block = ""

    home_scorers = parse_scorer_list(home_block)
    away_scorers = parse_scorer_list(away_block)

    return home_scorers, away_scorers, pens_score, pens_winner


def parse_scorer_list(text):
    """
    Parse a list of scorers.

    Format examples:
        "Mbappé 45' , 74' Barcola 53'"
        "Casemiro 56' Martinelli 90+5'"
        "Havertz 54' (pen.)"
        "Kane 75' , 86'"

    Returns list of {"name": str, "minute": int, "pen": bool, "raw": str}
    Note: a single player with multiple minutes (Mbappé 45' , 74') is recorded
    ONCE per name with the first minute; the additional minutes are tracked
    as "+ N', M'..." in raw.
    """
    if not text:
        return []
    name_pat = r"[A-Z][\w\u00c0-\u017f'\.\-]+(?:\s+[A-Z][\w\u00c0-\u017f'\.\-]+)*"
    # Single minute pattern (with optional +NN stoppage time and optional (pen.))
    single_minute = r"(\d+)(?:\s*\+\s*\d+)?\s*'(?:\s*\(\s*pen\.?\s*\))?"
    # A scorer entry: Name followed by 1+ minute marks separated by comma+space
    entry_pat = rf"({name_pat})\s+({single_minute}(?:\s*,\s*{single_minute})*)"
    out = []
    seen_names = set()
    for sm in re.finditer(entry_pat, text):
        name = sm.group(1).strip()
        if name in seen_names:
            # Already recorded; but collect additional minutes
            for entry in out:
                if entry["name"] == name:
                    entry["raw"] = sm.group(0).strip()
                    break
            continue
        seen_names.add(name)
        first_minute_match = re.match(single_minute, sm.group(2).split(",")[0].strip())
        minute = int(first_minute_match.group(1)) if first_minute_match else 0
        pen = "pen" in sm.group(0).lower()
        out.append({
            "name": name,
            "minute": minute,
            "pen": pen,
            "raw": sm.group(0).strip(),
        })
    return out


def fetch_espn(date_str=None):
    """
    Fetch ESPN scoreboard API for a given date (YYYY-MM-DD) or current if None.
    Returns list of completed matches with team names, scores, and scorers.
    """
    url = ESPN_API_URL
    if date_str:
        # Convert YYYY-MM-DD to YYYYMMDD-YYYYMMDD range
        compact = date_str.replace("-", "")
        url = f"{ESPN_API_URL}?dates={compact}-{compact}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"   ⚠️  Could not fetch ESPN: {e}", file=sys.stderr)
        return []
    matches = []
    for ev in data.get("events", []):
        comp = ev.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {})
        if not status.get("completed"):
            continue
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue
        home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        match = {
            "name": ev.get("name", ""),
            "home_name": home_c.get("team", {}).get("displayName", ""),
            "away_name": away_c.get("team", {}).get("displayName", ""),
            "home_score": int(home_c.get("score", 0)),
            "away_score": int(away_c.get("score", 0)),
            "status": status.get("description", ""),
            "details": [],
        }
        for d in comp.get("details", []):
            if not d.get("scoringPlay"):
                continue
            clock = d.get("clock", {}).get("displayValue", "")
            # Extract minute from "39'" or "90'+5'"
            minute_match = re.match(r"(\d+)", clock)
            minute = int(minute_match.group(1)) if minute_match else 0
            for ath in d.get("athletesInvolved", []):
                match["details"].append({
                    "name": ath.get("displayName", ath.get("shortName", "")),
                    "minute": minute,
                    "team_id": str(ath.get("team", {}).get("id", "")),
                })
        # Sort details by minute for readability
        match["details"].sort(key=lambda d: d["minute"])
        matches.append(match)
    return matches


def crossref_with_espn(json_matches, json_path):
    """
    Secondary cross-reference against ESPN scoreboard API.
    Fetches all match dates from the JSON and compares scores.

    Returns list of error strings. Empty = pass.
    """
    # Collect all match dates from JSON
    dates = set()
    for m in json_matches:
        d = m.get("date", "")
        if d:
            dates.add(d)
    if not dates:
        return []
    print(f"   Cross-referencing {len(json_matches)} matches against ESPN "
          f"({len(dates)} dates)...")
    espn_matches_by_date = {}
    for date in sorted(dates):
        espn_matches_by_date[date] = fetch_espn(date)
        print(f"   ESPN {date}: {len(espn_matches_by_date[date])} completed matches")
    errors = []
    for jm in json_matches:
        if jm["status"] not in ("FT", "FT-pens", "FT-aet"):
            continue
        h_name = jm["home"]["name"]
        a_name = jm["away"]["name"]
        h_goals = jm["home"]["goals"]
        a_goals = jm["away"]["goals"]
        # Find ESPN match
        espn_list = espn_matches_by_date.get(jm.get("date", ""), [])
        espn_match = None
        for em in espn_list:
            if ((team_matches(em["home_name"], h_name) and team_matches(em["away_name"], a_name)) or
                (team_matches(em["home_name"], a_name) and team_matches(em["away_name"], h_name))):
                espn_match = em
                break
        if not espn_match:
            # ESPN missing — don't error (could be API hasn't updated, or
            # match not yet indexed). Warn only.
            print(f"   ⚠️  M{jm['id']}: {h_name} vs {a_name} not found in ESPN",
                  file=sys.stderr)
            continue
        # Compare score (accept either direction)
        if not ((espn_match["home_score"] == h_goals and espn_match["away_score"] == a_goals) or
                (espn_match["home_score"] == a_goals and espn_match["away_score"] == h_goals)):
            errors.append(
                f"M{jm['id']}: {h_name} {h_goals}-{a_goals} {a_name} \u2014 "
                f"ESPN SAYS {espn_match['home_score']}-{espn_match['away_score']} "
                f"({espn_match['home_name']} v {espn_match['away_name']})"
            )
    return errors


def team_matches(a, b):
    """Loose team-name match (handles DR Congo, Côte d'Ivoire, USA/United States, etc.)."""
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
        # Bosnia: "and" vs "&" differ — handle explicitly
        "bosniaandherzegovina": "bosniaherzegovina",
        "bosniaherzegovina": "bosniaandherzegovina",
        # Abbreviations
        "usa": "unitedstates",
        "unitedstates": "usa",
        "uae": "unitedarabemirates",
        "unitedarabemirates": "uae",
        "uk": "unitedkingdom",
        "unitedkingdom": "uk",
        # Trinidad: "and" vs "&" differ
        "trinidadandtobago": "trinidadtobago",
        "trinidadtobago": "trinidadandtobago",
        # Antigua: same
        "antiguaandbarbuda": "antiguabarbuda",
        "antiguabarbuda": "antiguaandbarbuda",
        # St. variations
        "stkittsandnevis": "stkittsnevis",
        "stkittsnevis": "stkittsandnevis",
        "saintkittsandnevis": "saintkittsnevis",
        "saintkittsnevis": "saintkittsandnevis",
    }
    if alternates.get(a_norm) == b_norm or alternates.get(b_norm) == a_norm:
        return True
    # Substring match (must be at least 5 chars to avoid false matches)
    if len(a_norm) >= 5 and len(b_norm) >= 5:
        if a_norm in b_norm or b_norm in a_norm:
            return True
    return False


def parse_json_scorers(scorers_field):
    """
    Parse the JSON "scorers" field.

    Format examples:
        "Mbappé 45', 74', Barcola 53'"        -> home all, away empty
        "Casemiro 56', Martinelli 90+5'; Sano 29'"  -> home before ';' / away after
        "Kane 75', 86'; Cipenga 7'"           -> home before ';' / away after
        "(pens: Germany 3-4 Paraguay — Tah missed)" -> pens only, no scorers

    Returns: (home_scorers, away_scorers) where each is a list of
        {"name": str, "minute": int, "pen": bool}
    """
    if not scorers_field:
        return [], []

    # Split on ';' (semicolon-with-space separator used between home and away)
    # Strip parenthetical "(pens: ...)" annotations — they're not scorers
    cleaned = re.sub(r"\([^)]*pens[^)]*\)", "", scorers_field).strip()
    if not cleaned:
        return [], []

    parts = re.split(r";\s*", cleaned, maxsplit=1)
    home_part = parts[0]
    away_part = parts[1] if len(parts) > 1 else ""

    return parse_scorer_list(home_part), parse_scorer_list(away_part)


def scorer_name_matches(json_name, wiki_name):
    """Loose match for scorer names (handles diacritics, hyphens, accents)."""
    def norm(s):
        # Remove diacritics, lowercase, strip punctuation
        import unicodedata
        nfkd = unicodedata.normalize("NFKD", s)
        return re.sub(r"[^a-z]", "", nfkd.encode("ascii", "ignore").decode().lower())
    a, b = norm(json_name), norm(wiki_name)
    if a == b:
        return True
    # Allow one initial-only match (e.g. "I. Sarr" vs "Ismaila Sarr")
    if len(a) >= 2 and len(b) >= 2:
        if a in b or b in a:
            return True
    return False


def crossref_scorers(home_name, away_name, json_home, json_away, wiki_home, wiki_away):
    """
    Compare JSON scorers vs Wikipedia scorers.

    Returns list of error strings (empty = pass). Tolerance: ±2 minutes.
    Each JSON scorer must find a matching Wikipedia scorer (same name + close minute).
    Extra wiki scorers not in JSON are warnings (not errors) — JSON may legitimately
    omit a scorer's name even when Wikipedia lists it.
    """
    errors = []

    def _check_team(team_name, json_list, wiki_list):
        matched_wiki_idxs = set()
        for js in json_list:
            # Try to find a matching wiki scorer (name + close minute)
            found = False
            for i, ws in enumerate(wiki_list):
                if i in matched_wiki_idxs:
                    continue
                if not scorer_name_matches(js["name"], ws["name"]):
                    continue
                # Within ±2 minutes tolerance
                if abs(js["minute"] - ws["minute"]) <= 2:
                    found = True
                    matched_wiki_idxs.add(i)
                    break
            if not found:
                # Try just name match (minute too far off)
                name_only = False
                for i, ws in enumerate(wiki_list):
                    if scorer_name_matches(js["name"], ws["name"]):
                        # Name matches but minute is way off
                        errors.append(
                            f"  {team_name}: scorer '{js['name']}' minute {js['minute']}' "
                            f"\u2014 Wikipedia says minute {ws['minute']}' "
                            f"(diff {abs(js['minute'] - ws['minute'])} min)"
                        )
                        matched_wiki_idxs.add(i)
                        name_only = True
                        break
                if not name_only:
                    wiki_names = [ws['name'] + ' ' + str(ws['minute']) + "'" for ws in wiki_list]
                    errors.append(
                        f"  {team_name}: scorer '{js['name']}' {js['minute']}' "
                        f"\u2014 NOT FOUND in Wikipedia (wiki has: {wiki_names})"
                    )
        # Note: extra wiki scorers not flagged as errors — JSON may legitimately
        # abbreviate. Just a silent warning.

    _check_team(home_name, json_home, wiki_home)
    _check_team(away_name, json_away, wiki_away)
    return errors


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

    section, phase_name = extract_phase_section(wiki_text)
    if section is None:
        print("❌  Could not find any phase section in Wikipedia", file=sys.stderr)
        print("    The page structure may have changed — update this script.", file=sys.stderr)
        return 3
    print(f"   Phase detected: {phase_name}")

    matches = parse_match_reports(section)
    if not matches:
        print(f"❌  Parsed 0 match reports from {phase_name} section", file=sys.stderr)
        print("    The page structure may have changed — update this script.", file=sys.stderr)
        return 3

    print(f"   Found {len(matches)} unique {phase_name} match reports from Wikipedia")

    # Cross-reference each completed match in our JSON
    errors = []
    json_matches = [m for m in data["matches"] if m["status"] in ("FT", "FT-pens", "FT-aet")]
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
            continue  # Skip scorer/pens checks if score itself is wrong

        # Cross-reference scorer names + minute marks
        # Match may have home/away swapped vs JSON, so build a canonical
        # scorer pair using whichever direction matches.
        if team_matches(match["home"], h_name):
            wiki_home_scorers = match["home_scorers"]
            wiki_away_scorers = match["away_scorers"]
            wiki_pens_winner = match["pens_winner"]
            wiki_pens_score = match["pens_score"]
        else:
            wiki_home_scorers = match["away_scorers"]
            wiki_away_scorers = match["home_scorers"]
            wiki_pens_winner = "home" if match["pens_winner"] == "away" else "away" if match["pens_winner"] == "home" else None
            wiki_pens_score = (match["pens_score"][1], match["pens_score"][0]) if match["pens_score"] else None

        # Parse JSON scorers from "scorers" field like
        # "Mbappé 45', 74', Barcola 53'" or
        # "Casemiro 56', Martinelli 90+5'; Sano 29'"
        json_scorers_field = jm.get("scorers", "") or ""
        json_home, json_away = parse_json_scorers(json_scorers_field)

        scorer_errors = crossref_scorers(
            h_name, a_name,
            json_home, json_away,
            wiki_home_scorers, wiki_away_scorers,
        )
        errors.extend(scorer_errors)

        # CROSS-CHECK: if a team scored 0 goals, they MUST have 0 scorers.
        # This catches "scorers assigned to wrong team" bugs even when
        # the score is just reversed (3-0 vs 0-3 with swapped scorer field).
        if h_goals == 0 and json_home:
            errors.append(
                f"M{jm['id']}: {h_name} scored 0 goals but JSON lists "
                f"scorers: {[s['name'] for s in json_home]}"
            )
        if a_goals == 0 and json_away:
            errors.append(
                f"M{jm['id']}: {a_name} scored 0 goals but JSON lists "
                f"scorers: {[s['name'] for s in json_away]}"
            )
        # Conversely: if a team scored N>0 goals, JSON should have N scorers
        if h_goals > 0 and len(json_home) != h_goals:
            # Allow some slack for own goals or aggregated scorer entries
            # (e.g. "Mbappé 45', 74'" is 1 entry but 2 goals). So check
            # at least 1 scorer is present, but don't require exact count.
            if len(json_home) == 0:
                errors.append(
                    f"M{jm['id']}: {h_name} scored {h_goals} goals but JSON "
                    f"lists no home scorers"
                )

        # Cross-reference penalty shootout winner for FT-pens matches
        if jm["status"] == "FT-pens":
            claimed_pens_winner = jm.get("penalty_winner", "").strip()
            if wiki_pens_winner and claimed_pens_winner:
                wiki_winner_name = h_name if wiki_pens_winner == "home" else a_name
                if not team_matches(wiki_winner_name, claimed_pens_winner):
                    errors.append(
                        f"M{jm['id']}: penalty winner '{claimed_pens_winner}' \u2014 "
                        f"WIKIPEDIA SAYS '{wiki_winner_name}' won "
                        f"({wiki_pens_score[0]}-{wiki_pens_score[1]} on pens)"
                    )
            elif wiki_pens_winner and not claimed_pens_winner:
                wiki_winner_name = h_name if wiki_pens_winner == "home" else a_name
                errors.append(
                    f"M{jm['id']}: penalty_winner missing \u2014 "
                    f"WIKIPEDIA SAYS '{wiki_winner_name}' won on pens"
                )
            elif not wiki_pens_winner and claimed_pens_winner:
                # JSON claims FT-pens but Wikipedia doesn't show a Penalties
                # section. This could mean (a) Wikipedia hasn't updated yet,
                # or (b) the match was actually FT-aet, not FT-pens.
                # Flag for manual review.
                errors.append(
                    f"M{jm['id']}: claims FT-pens (winner '{claimed_pens_winner}') "
                    f"\u2014 WIKIPEDIA HAS NO PENALTIES SECTION "
                    f"(match may be FT-aet, not FT-pens; verify)"
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

    # SECONDARY: ESPN API cross-reference (triangulation)
    print()
    print("Fetching ESPN secondary source...")
    espn_errors = crossref_with_espn(json_matches, json_path)
    if espn_errors:
        print()
        print("\u274C  ESPN DATA MISMATCH \u2014 push blocked", file=sys.stderr)
        for e in espn_errors:
            print(f"  \u2022 {e}", file=sys.stderr)
        print()
        print("Wikipedia passed but ESPN disagrees. Investigate before pushing.",
              file=sys.stderr)
        return 1
    print("   \u2705  ESPN cross-reference passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
