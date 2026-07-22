from pathlib import Path


template = Path("tokyo/site_template/index.html").read_text(encoding="utf-8")
beacon = "https://static.cloudflareinsights.com/beacon.min.js"

assert template.count(beacon) == 1
assert template.index(beacon) < template.index("</body>")
