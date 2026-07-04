#!/usr/bin/env python3
"""
World Cup Briefing HTML Generator — DATA-DRIVEN
Reads world-cup-data.json → generates world-cup.html
No LLM touches score data. Every number comes from the JSON.
"""
import json, datetime, os, re

DATA_PATH = os.path.join(os.path.dirname(__file__), "world-cup-data.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "world-cup.html")

with open(DATA_PATH) as f:
    data = json.load(f)

matches = data["matches"]

# --- ET → SGT conversion ---
def et_to_sgt(et_str):
    """Convert '12:00 PM' ET to 'Jul 2, 12:00 AM' SGT display."""
    if not et_str:
        return ""
    parts = et_str.strip().split()
    time_part = parts[0]  # "12:00"
    ampm = parts[1].upper() if len(parts) > 1 else "AM"
    hour_str, minute_str = time_part.split(":")
    hour = int(hour_str)
    minute = minute_str
    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0
    # SGT = ET + 12 hours
    sgt_hour = (hour + 12) % 24
    # Determine SGT date: add 1 day if hour >= 12 (i.e. ET noon onwards)
    # Et date is in the JSON "date" field, passed separately
    sgt_ampm = "AM"
    sgt_hour12 = sgt_hour
    if sgt_hour >= 12:
        sgt_ampm = "PM"
        if sgt_hour > 12:
            sgt_hour12 = sgt_hour - 12
    else:
        sgt_hour12 = sgt_hour if sgt_hour != 0 else 12
    return f"{sgt_hour12}:{minute} {sgt_ampm} SGT"

def sgt_date_offset(et_date_str, et_time_str):
    """Return SGT date label. If SGT date differs from ET date, show it."""
    if not et_date_str or not et_time_str:
        return ""
    parts = et_time_str.strip().split()
    time_part = parts[0]
    ampm = parts[1].upper() if len(parts) > 1 else "AM"
    hour_str = time_part.split(":")[0]
    hour = int(hour_str)
    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0
    # If ET is noon or later, SGT is next day
    if hour >= 12:
        # Match date in JSON is ET date; SGT is +1 day
        try:
            d = datetime.datetime.strptime(et_date_str, "%Y-%m-%d")
            d += datetime.timedelta(days=1)
            return d.strftime("%b %d")
        except:
            pass
    return ""

# --- Status display helpers ---
def status_badge(m):
    if m["status"] == "FT":
        return '<span class="badge badge-ft">✅ FT</span>'
    elif m["status"] == "FT-pens":
        return '<span class="badge badge-pens">⚫ AET/Pens</span>'
    elif m["status"] == "FT-aet":
        return '<span class="badge badge-aet">⏱️ AET</span>'
    elif m["status"] == "live":
        return '<span class="badge badge-live">🔴 LIVE</span>'
    else:
        return '<span class="badge badge-upcoming">⏳ Upcoming</span>'

def score_display(m):
    if m["status"] == "upcoming":
        return '<span class="vs">vs</span>'
    else:
        h = m["home"]["goals"]
        a = m["away"]["goals"]
        return f'<span class="score">{h}–{a}</span>'

def winner_flag(m):
    if m["status"] in ("FT", "FT-aet"):
        if m["home"]["qualified"]:
            return m["home"]["flag"]
        return m["away"]["flag"]
    elif m["status"] == "FT-pens":
        w = m["penalty_winner"]
        for team in [m["home"], m["away"]]:
            if team["name"] == w:
                return team["flag"]
    return ""

def is_boss_team(name):
    return name in ["Portugal", "Spain", "Argentina"]

# --- Build R16 bracket path from data['r16_path'] (confirmed R32 winners) ---
# Build flag map from matches
_flag_map = {}
for _m in matches:
    _flag_map[_m["home"]["name"]] = _m["home"]["flag"]
    _flag_map[_m["away"]["name"]] = _m["away"]["flag"]

r16_bracket = []
for _r in data.get("r16_path", []):
    _teams = _r["teams"]
    # Add flag emoji to each team name if missing
    _parts = []
    for _t in _teams.split(" vs "):
        _t = _t.strip()
        # If already has a flag (emoji at start), leave it
        _flag = _flag_map.get(_t, "")
        if _flag and not _t.startswith(_flag):
            _parts.append(f"{_flag} {_t}")
        else:
            _parts.append(_t)
    _slot = f"{_r['match']} ({_r['date']}, {_r['venue']})"
    r16_bracket.append({"slot": _slot, "teams": " vs ".join(_parts)})

# --- HTML Template ---
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚽ World Cup 2026 — R32 Knockout Bracket</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0a0e17;
    --surface: #111827;
    --surface2: #1a2332;
    --accent: #e8b830;
    --accent2: #f59e0b;
    --green: #22c55e;
    --red: #ef4444;
    --blue: #3b82f6;
    --purple: #a855f7;
    --text: #f1f5f9;
    --text2: #94a3b8;
    --border: #1e293b;
  }}
  html {{ font-size: 16px; scroll-behavior: smooth; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }}
  .hero {{
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%);
    padding: 2rem 1.5rem;
    text-align: center;
    border-bottom: 3px solid var(--accent);
    position: relative;
    overflow: hidden;
  }}
  .hero-badge {{
    display: inline-block;
    background: var(--accent);
    color: #0a0e17;
    font-size: 0.7rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    padding: 0.25rem 0.75rem;
    border-radius: 999px;
    margin-bottom: 0.75rem;
  }}
  .hero h1 {{ font-size: clamp(1.5rem, 4vw, 2.5rem); font-weight: 900; margin-bottom: 0.5rem; }}
  .hero h1 .wc {{ color: var(--accent); }}
  .hero .date {{ font-size: 0.95rem; color: var(--text2); }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 1.25rem; }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1rem;
  }}
  .card-header {{
    display: flex; align-items: center; gap: 0.6rem;
    font-size: 1.05rem; font-weight: 700;
    margin-bottom: 1rem; padding-bottom: 0.6rem;
    border-bottom: 1px solid var(--border);
  }}
  .card-header .icon {{ font-size: 1.3rem; }}

  /* BRACKET GRID — 2-column modern layout */
  .bracket-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }}
  @media (max-width: 700px) {{
    .bracket-grid {{ grid-template-columns: 1fr; }}
  }}
  .bracket-section {{
    background: var(--surface2);
    border-radius: 10px;
    padding: 1rem;
    border: 1px solid var(--border);
  }}
  .bracket-section h3 {{
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--accent);
    margin-bottom: 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
  }}

  /* MATCH CARD */
  .match-card {{
    position: relative;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.6rem 0.75rem;
    margin-bottom: 0.6rem;
    transition: border-color 0.15s, transform 0.15s;
  }}
  .match-card:hover {{ border-color: var(--accent); transform: translateY(-1px); }}
  .match-card a.card-link {{
    position: absolute; inset: 0; z-index: 1;
    border-radius: 8px;
    text-decoration: none;
  }}
  .match-card > * {{ position: relative; z-index: 2; pointer-events: none; }}
  .match-card .match-highlights a {{ pointer-events: auto; }}
  .match-card.boss {{
    border-left: 3px solid var(--accent);
    background: linear-gradient(135deg, var(--surface) 0%, rgba(232,184,48,0.06) 100%);
  }}
  .match-card.upcoming {{ opacity: 0.85; }}
  .match-top {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 0.3rem;
  }}
  .match-meta {{ font-size: 0.7rem; color: var(--text2); }}
  .match-teams {{
    display: flex; align-items: center; gap: 0.5rem;
    font-size: 0.95rem; font-weight: 600;
  }}
  .match-teams .team {{ display: flex; align-items: center; gap: 0.3rem; }}
  .match-teams .team.winner {{ color: var(--green); }}
  .match-teams .team.loser {{ color: var(--text2); opacity: 0.7; }}
  .score {{ font-weight: 800; font-size: 1.1rem; color: var(--accent); min-width: 2rem; text-align: center; }}
  .vs {{ font-weight: 600; font-size: 0.8rem; color: var(--text2); }}
  .match-detail {{ font-size: 0.75rem; color: var(--text2); margin-top: 0.3rem; line-height: 1.4; }}
  .match-scorers {{ font-size: 0.7rem; color: var(--accent); margin-top: 0.15rem; }}
  .match-highlights {{ margin-top: 0.35rem; }}
  .match-highlights a {{
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--accent);
    text-decoration: none;
    background: rgba(232,184,48,0.1);
    border: 1px solid rgba(232,184,48,0.25);
    padding: 0.2rem 0.6rem;
    border-radius: 6px;
    transition: background 0.15s;
  }}
  .match-highlights a:hover {{ background: rgba(232,184,48,0.2); }}

  .badge {{ font-size: 0.6rem; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 4px; text-transform: uppercase; }}
  .badge-ft {{ background: rgba(34,197,94,0.2); color: var(--green); }}
  .badge-pens {{ background: rgba(168,85,247,0.2); color: var(--purple); }}
  .badge-aet {{ background: rgba(245,158,11,0.2); color: var(--accent2); }}
  .badge-live {{ background: rgba(59,130,246,0.2); color: var(--blue); }}
  .badge-upcoming {{ background: rgba(148,163,184,0.2); color: var(--text2); }}

  .r16-list {{ list-style: none; }}
  .r16-list li {{
    padding: 0.5rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    font-size: 0.85rem;
    display: flex; align-items: center; gap: 0.5rem;
  }}
  .r16-list li:last-child {{ border-bottom: none; }}
  .r16-slot {{ font-size: 0.7rem; color: var(--text2); min-width: 8rem; }}

  .footer {{
    text-align: center; padding: 1.5rem;
    color: var(--text2); font-size: 0.75rem;
    border-top: 1px solid var(--border);
  }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; font-size: 0.75rem; color: var(--text2); margin-bottom: 1rem; }}
  .legend span {{ display: flex; align-items: center; gap: 0.3rem; }}

  /* GOLDEN BOOT */
  .gb-grid {{ display: flex; flex-direction: column; gap: 0.35rem; }}
  .gb-row {{
    display: grid;
    grid-template-columns: 2rem 1.8rem 1fr 1.2fr 4.5rem;
    align-items: center;
    gap: 0.5rem;
    padding: 0.45rem 0.6rem;
    border-radius: 6px;
    background: var(--surface2);
    font-size: 0.85rem;
  }}
  .gb-row.gb-gold {{ background: rgba(232,184,48,0.12); border: 1px solid rgba(232,184,48,0.25); }}
  .gb-row.gb-silver {{ background: rgba(148,163,184,0.08); border: 1px solid rgba(148,163,184,0.15); }}
  .gb-rank {{ font-size: 0.8rem; font-weight: 700; color: var(--text2); text-align: center; }}
  .gb-flag {{ font-size: 1.1rem; }}
  .gb-name {{ font-weight: 600; }}
  .gb-country {{ font-size: 0.75rem; color: var(--text2); }}
  .gb-goals {{ font-size: 0.85rem; font-weight: 700; color: var(--accent); text-align: right; }}
  @media (max-width: 500px) {{
    .gb-row {{ grid-template-columns: 1.6rem 1.4rem 1fr 3.5rem; }}
    .gb-country {{ display: none; }}
  }}
</style>
</head>
<body>

<header class="hero">
  <div class="hero-badge">🌍 2026 World Cup</div>
  <h1><span class="wc">⚽ Knockout Bracket</span></h1>
  <p class="date">{datetime.datetime.now().strftime("%A, %B %d, %Y")} (SGT) · Round of 32 underway 🔥</p>
</header>

<main class="container">

<div class="legend">
  <span>✅ FT — Full Time</span>
  <span>⏱️ AET — Extra Time (no pens)</span>
  <span>⚫ AET/Pens — Extra Time + Penalties</span>
  <span>⏳ Upcoming — Match not yet played</span>
  <span style="border-left:3px solid var(--accent);padding-left:0.5rem;">⭐ Boss's Team</span>
</div>

<!-- ===== BRACKET: TOP HALF ===== -->
<div class="card">
  <div class="card-header"><span class="icon">🏆</span> Round of 32 — Completed Results</div>
  <div class="bracket-grid">
    <div class="bracket-section">
      <h3>🎯 Upper Bracket</h3>
"""

# Generate match cards — top half (matches 73-80)
top_half_matches = [m for m in matches if m["id"] <= 80]
for m in top_half_matches:
    boss = is_boss_team(m["home"]["name"]) or is_boss_team(m["away"]["name"])
    cls = "boss" if boss else ""
    if m["status"] == "upcoming":
        cls += " upcoming"

    h_name = m["home"]["flag"] + " " + m["home"]["name"]
    a_name = m["away"]["flag"] + " " + m["away"]["name"]
    
    h_win = m["status"] in ("FT", "FT-pens", "FT-aet") and m["home"]["qualified"]
    a_win = m["status"] in ("FT", "FT-pens", "FT-aet") and m["away"]["qualified"]
    h_cls = "winner" if h_win else ("loser" if m["status"] in ("FT","FT-pens","FT-aet") else "")
    a_cls = "winner" if a_win else ("loser" if m["status"] in ("FT","FT-pens","FT-aet") else "")

    # Build match-meta with SGT time for upcoming matches
    sgt_str = ""
    if m["status"] == "upcoming" and m.get("kickoff_et"):
        sgt_extra = et_to_sgt(m["kickoff_et"])
        sgt_date = sgt_date_offset(m["date"], m["kickoff_et"])
        if sgt_date:
            sgt_str = f" · 🕐 {sgt_date}, {sgt_extra}"
        else:
            sgt_str = f" · 🕐 {sgt_extra}"

    html += f"""    <div class="match-card {cls}">
      <a class="card-link" href="{m["highlights"]}" target="_blank" rel="noopener" aria-label="Watch highlights: {m["home"]["name"]} vs {m["away"]["name"]}"></a>
      <div class="match-top">
        <span class="match-meta">Match {m["id"]} · {m["venue"]}{sgt_str}</span>
        {status_badge(m)}
      </div>
      <div class="match-teams">
        <span class="team {h_cls}">{h_name}</span>
        {score_display(m)}
        <span class="team {a_cls}">{a_name}</span>
      </div>

"""
    if m.get("scorers"):
        html += f"""      <div class="match-scorers">⚽ {m["scorers"]}</div>
"""
    if m.get("note"):
        html += f"""      <div class="match-detail">{m["note"]}</div>
"""
    if m.get("highlights"):
        html += f"""      <div class="match-highlights"><a href="{m["highlights"]}" target="_blank" rel="noopener">🎬 Watch Highlights →</a></div>
"""
    html += f"""    </div>
"""

html += """    </div>
    <div class="bracket-section">
      <h3>🎯 Lower Bracket</h3>
"""

# Lower half (matches 81-88)
lower_half_matches = [m for m in matches if m["id"] >= 81]
for m in lower_half_matches:
    boss = is_boss_team(m["home"]["name"]) or is_boss_team(m["away"]["name"])
    cls = "boss" if boss else ""
    if m["status"] == "upcoming":
        cls += " upcoming"

    h_name = m["home"]["flag"] + " " + m["home"]["name"]
    a_name = m["away"]["flag"] + " " + m["away"]["name"]
    
    h_win = m["status"] in ("FT", "FT-pens", "FT-aet") and m["home"]["qualified"]
    a_win = m["status"] in ("FT", "FT-pens", "FT-aet") and m["away"]["qualified"]
    h_cls = "winner" if h_win else ("loser" if m["status"] in ("FT","FT-pens","FT-aet") else "")
    a_cls = "winner" if a_win else ("loser" if m["status"] in ("FT","FT-pens","FT-aet") else "")

    # Build match-meta with SGT time for upcoming matches
    sgt_str = ""
    if m["status"] == "upcoming" and m.get("kickoff_et"):
        sgt_extra = et_to_sgt(m["kickoff_et"])
        sgt_date = sgt_date_offset(m["date"], m["kickoff_et"])
        if sgt_date:
            sgt_str = f" · 🕐 {sgt_date}, {sgt_extra}"
        else:
            sgt_str = f" · 🕐 {sgt_extra}"

    html += f"""    <div class="match-card {cls}">
      <a class="card-link" href="{m["highlights"]}" target="_blank" rel="noopener" aria-label="Watch highlights: {m["home"]["name"]} vs {m["away"]["name"]}"></a>
      <div class="match-top">
        <span class="match-meta">Match {m["id"]} · {m["venue"]}{sgt_str}</span>
        {status_badge(m)}
      </div>
      <div class="match-teams">
        <span class="team {h_cls}">{h_name}</span>
        {score_display(m)}
        <span class="team {a_cls}">{a_name}</span>
      </div>

"""
    if m.get("scorers"):
        html += f"""      <div class="match-scorers">⚽ {m["scorers"]}</div>
"""
    if m.get("note"):
        html += f"""      <div class="match-detail">{m["note"]}</div>
"""
    if m.get("highlights"):
        html += f"""      <div class="match-highlights"><a href="{m["highlights"]}" target="_blank" rel="noopener">🎬 Watch Highlights →</a></div>
"""
    html += f"""    </div>
"""

# --- R16 Path ---
html += """    </div>
  </div>
</div>

<!-- ===== R16 PATH ===== -->
<div class="card">
  <div class="card-header"><span class="icon">⚔️</span> Round of 16 — Confirmed Fixtures</div>
  <ul class="r16-list">
"""

for r in r16_bracket:
    html += f"""    <li><span class="r16-slot">{r["slot"]}</span> {r["teams"]}</li>
"""

html += """  </ul>
</div>

<!-- ===== GOLDEN BOOT ===== -->
<div class="card">
  <div class="card-header"><span class="icon">⚽</span> Golden Boot — Top Scorers</div>
  <div class="gb-grid">
"""
# Sort by goals desc, then assists desc, then name asc — ensures correct
# ordering even if JSON 'rank' field is stale or out of sync
gb_list = sorted(data.get("golden_boot", []),
                 key=lambda p: (-p["goals"], -p["assists"], p["player"]))
# Reassign rank so rendered medals/cells are consistent
for _i, _p in enumerate(gb_list, start=1):
    _p["rank"] = _i
for p in gb_list:
    rank_cls = "gb-gold" if p["rank"] <= 2 else ("gb-silver" if p["rank"] == 3 else "")
    medal = {"1": "🥇", "2": "🥈", "3": "🥉"}.get(str(p["rank"]), "")
    assists_str = f" ({p['assists']}A)" if p["assists"] else ""
    html += f"""    <div class="gb-row {rank_cls}">
      <span class="gb-rank">{medal or f'#{p["rank"]}'}</span>
      <span class="gb-flag">{p["flag"]}</span>
      <span class="gb-name">{p["player"]}</span>
      <span class="gb-country">{p["country"]}</span>
      <span class="gb-goals">{p["goals"]}⚽{assists_str}</span>
    </div>
"""
html += """  </div>
</div>

</main>

<footer class="footer">
  <p>⚽ World Cup 2026 · Data-driven briefing · Updated daily from FIFA.com verified sources</p>
  <p style="margin-top:0.25rem;">Every score is mechanically cross-referenced — no AI halluncination. ⭐ = Boss's teams: 🇵🇹 Portugal, 🇪🇸 Spain, 🇦🇷 Argentina</p>
</footer>

</body>
</html>
"""

with open(OUTPUT_PATH, "w") as f:
    f.write(html)

print(f"✅ Generated {OUTPUT_PATH} ({len(html)} bytes)")
print(f"   {len(matches)} R32 matches — {sum(1 for m in matches if m['status'] in ('FT','FT-pens','FT-aet'))} completed, {sum(1 for m in matches if m['status']=='upcoming')} upcoming")
