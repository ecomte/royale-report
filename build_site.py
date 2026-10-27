#!/usr/bin/env python3
"""
Build the hosted Royale Report site (what GitHub Actions runs).

  python3 build_site.py               # fetch new battles, then build site/
  python3 build_site.py --no-fetch    # build from the saved CSVs only
  python3 build_site.py --no-fetch --serve   # build, then serve at http://localhost:8000

For every page in config.json it pulls new battles (cr_collect.py), renders
the dashboard (cr_dashboard.py), and wraps it with the player switch and the
Refresh button (web/). One player's fetch failing doesn't stop the build;
their page just shows the battles already saved. Standard library only.
"""

import argparse
import http.server
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the folder

from cr_collect import CollectError, collect, load_players, read_token, stamp, summary_line

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
WEB = HERE / "web"

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a1838">
<link rel="icon" href="../web/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../web/refresh.css">
<script>window.RR = {rr};</script>
<script src="../web/refresh.js"></script>
"""

INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Royale Report</title>
<meta http-equiv="refresh" content="0; url={first}/">
<script>location.replace("{first}/" + location.hash);</script>
</head>
<body style="background:#0a1838;color:#eef4ff;font-family:system-ui,sans-serif">
<p><a href="{first}/" style="color:#ffd23f">Open The Royale Report</a></p>
</body>
</html>
"""


def fetch_all(pages):
    """Pull new battles for every page's player. Returns {player: "ok" | error text}."""
    try:
        players = load_players()
        token = read_token()
    except CollectError as e:
        print(f"[{stamp()}] Not fetching: {e}")
        return {p["player"]: str(e) for p in pages}
    status = {}
    for p in pages:
        name = p["player"]
        try:
            print("  " + summary_line(collect(name, players[name], token)))
            status[name] = "ok"
        except (CollectError, KeyError) as e:
            print(f"  {name:<8} FAILED: {e}")
            status[name] = str(e)
    return status


def build(site, config, fetched):
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(WEB, site / "web")
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nav = [{"name": p["name"], "path": p["path"]} for p in config["pages"]]
    for p in config["pages"]:
        out = site / p["path"] / "index.html"
        out.parent.mkdir(parents=True)
        subprocess.run([sys.executable, str(HERE / "cr_dashboard.py"), p["player"],
                        "--name", p["name"], "--out", str(out)], check=True)
        rr = {
            "repo": config["repo"], "workflow": config["workflow"], "branch": config["branch"],
            "pages": nav, "current": p["path"], "generated": generated,
            "fetch": fetched.get(p["player"], "skipped"),
        }
        blob = json.dumps(rr, separators=(",", ":")).replace("</", "<\\/")
        # The template is a page body (no <html>/<head>), so give it a proper document head.
        out.write_text(HEAD.replace("{rr}", blob) + out.read_text(encoding="utf-8"), encoding="utf-8")
    (site / "index.html").write_text(INDEX.replace("{first}", config["pages"][0]["path"]), encoding="utf-8")
    (site / "status.json").write_text(json.dumps({"generated": generated, "fetch": fetched}, indent=2))
    (site / ".nojekyll").write_text("")
    print(f"[{stamp()}] Built {len(config['pages'])} pages into {site}")


def main():
    ap = argparse.ArgumentParser(description="Build the hosted Royale Report site.")
    ap.add_argument("--no-fetch", action="store_true", help="don't call the API, use the saved CSVs")
    ap.add_argument("--site", default="site", help="output folder (default: site)")
    ap.add_argument("--serve", action="store_true", help="serve the site at http://localhost:8000 afterward")
    args = ap.parse_args()

    config = json.loads(CONFIG.read_text())
    fetched = {} if args.no_fetch else fetch_all(config["pages"])
    site = (HERE / args.site).resolve()
    if site in (HERE, *HERE.parents):
        sys.exit(f"--site {args.site} would wipe the project folder. Pick an empty folder.")
    build(site, config, fetched)

    if args.serve:
        handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
        print("Serving at http://localhost:8000 (Ctrl+C to stop)")
        try:
            http.server.ThreadingHTTPServer(("127.0.0.1", 8000), handler).serve_forever()
        except KeyboardInterrupt:
            pass

    # A failed fetch still publishes the saved battles; flag it on the Actions run.
    if os.environ.get("GITHUB_ACTIONS"):
        for name, res in fetched.items():
            if res != "ok":
                print(f"::warning title=No new battles for {name}::{res}")


if __name__ == "__main__":
    main()
