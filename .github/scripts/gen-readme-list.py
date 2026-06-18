#!/usr/bin/env python3
"""Generate file list and inject into README.md between AUTO-LIST markers."""
import os
import sys

repo_root = "."
site_url = "https://yonghuatrc.github.io/pages/"
readme_path = "README.md"
start_marker = "<!-- AUTO-LIST-START -->"
end_marker = "<!-- AUTO-LIST-END -->"

# Build the new block
lines = []
lines.append(start_marker)
lines.append("## Files")
lines.append("")
html_files = sorted(f for f in os.listdir(repo_root) if f.endswith(".html"))
if html_files:
    for f in html_files:
        lines.append(f"- [{f}]({site_url}{f})")
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

print("README.md updated")
