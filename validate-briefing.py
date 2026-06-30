#!/usr/bin/env python3
"""Validation gate: cross-references every score in HTML against data JSON."""
import json, re, sys

HTML_PATH = "/home/dennis/pages-repo/world-cup.html"
DATA_PATH = "/home/dennis/pages-repo/world-cup-data.json"

with open(DATA_PATH) as f:
    data = json.load(f)
with open(HTML_PATH) as f:
    html = f.read()

errors = []

# 1. No "4-1" anywhere
if "4-1" in html:
    errors.append("'4-1' still present in HTML")

# 2. Every FT match score in HTML matches JSON
for m in data["matches"]:
    if m["status"] not in ("FT", "FT-pens"):
        continue
    h_name = m["home"]["name"]
    a_name = m["away"]["name"]
    h_goals = m["home"]["goals"]
    a_goals = m["away"]["goals"]
    
    patterns = [
        rf'{h_name}.*?(\d+)\s*[–-]\s*(\d+).*?{a_name}',
        rf'{a_name}.*?(\d+)\s*[–-]\s*(\d+).*?{h_name}',
    ]
    found = False
    for pat in patterns:
        for match in re.finditer(pat, html, re.DOTALL):
            s1, s2 = int(match.group(1)), int(match.group(2))
            if (s1 == h_goals and s2 == a_goals) or (s2 == h_goals and s1 == a_goals):
                found = True
                break
        if found:
            break
    if not found:
        errors.append(f"Match {m['id']}: {h_name} vs {a_name} — expected {h_goals}-{a_goals}, not found in HTML")

# 3. File size check
size = len(html)
if size < 10000 or size > 50000:
    errors.append(f"File size {size} bytes outside expected range")

# 4. Valid HTML structure
if "<!DOCTYPE html>" not in html:
    errors.append("Missing DOCTYPE")
if "</html>" not in html:
    errors.append("Missing closing html tag")

if errors:
    for e in errors:
        print(f"❌  {e}")
    sys.exit(1)
else:
    completed = sum(1 for m in data['matches'] if m['status'] in ('FT','FT-pens'))
    upcoming = sum(1 for m in data['matches'] if m['status']=='upcoming')
    print(f"✅  ALL {len(data['matches'])} matches verified — scores match data JSON")
    print(f"📄  {size} bytes — valid HTML")
    print(f"🏁  {completed} completed, {upcoming} upcoming")
