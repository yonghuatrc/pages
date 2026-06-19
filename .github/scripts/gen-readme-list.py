#!/usr/bin/env python3
"""Generate file list and inject into README.md between AUTO-LIST markers.

Auto-detects the GitHub Pages URL from the git remote origin.
"""
import os
import subprocess
import sys

readme_path = "README.md"
start_marker = "<!-- AUTO-LIST-START -->"
end_marker = "<!-- AUTO-LIST-END -->"

# Auto-detect Pages URL from git remote
try:
    remote = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        capture_output=True, text=True, check=True, timeout=5
    ).stdout.strip()
    # Parse: https://github.com/user/repo.git or git@github.com:user/repo.git
    if remote.endswith(".git"):
        remote = remote[:-4]
    if remote.startswith("https://github.com/"):
        repo_path = remote[len("https://github.com/"):]
    elif remote.startswith("git@github.com:"):
        repo_path = remote[len("git@github.com:"):]
    else:
        repo_path = ""
    # GitHub Pages URL for user/org repos: https://<user>.github.io/<repo>/
    parts = repo_path.split("/")
    if len(parts) == 2:
        user, repo = parts
        site_url = f"https://{user}.github.io/{repo}/"
    else:
        site_url = ""
except Exception:
    site_url = ""

# Build the new block
lines = []
lines.append(start_marker)
lines.append("## Files")
lines.append("")
html_files = sorted(f for f in os.listdir(".") if f.endswith(".html"))
if html_files:
    for f in html_files:
        url = f"{site_url}{f}" if site_url else f
        lines.append(f"- [{f}]({url})")
else:
    lines.append("*(no HTML files yet)*")
lines.append("")
lines.append(end_marker)
new_block = "\n".join(lines)

# Read current README
with open(readme_path) as f:
    readme = f.read()

# Find markers and replace
start = readme.find(start_marker)
end = readme.find(end_marker)
if start == -1 or end == -1:
    print("ERROR: markers not found in README.md")
    sys.exit(1)

new_readme = readme[:start] + new_block + readme[end + len(end_marker):]
with open(readme_path, "w") as f:
    f.write(new_readme)

print(f"README.md updated (site: {site_url})")
