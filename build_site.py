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
import html
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

from cr_collect import DATA_DIR, CollectError, collect, load_players, read_token, stamp, summary_line
from cr_dashboard import load_battles

HERE = Path(__file__).resolve().parent
KEEP_UPDATES = 200   # refresh history entries kept per player (data/<player>/updates.json)
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
<script src="../web/news.js"></script>
"""

LANDING = HERE / "landing_template.html"

# Bottom of every player page (and the landing page): what isn't counted, version, copyright.
FOOTER = """
<footer class="rr-foot">
  <p>This version doesn't include Clan Wars boat battles or duels. Those modes are skipped for every player, so they aren't in any stats or the battle log.</p>
  <p><a href="https://github.com/{repo}/releases">v{version}</a> · © 2026 E Comte · <a href="https://github.com/{repo}/blob/main/COPYRIGHT.md">Copyright</a></p>
  <p>Not affiliated with, endorsed, sponsored, or specifically approved by Supercell. <a href="https://supercell.com/en/fan-content-policy/">Fan Content Policy</a></p>
</footer>
"""

CARD = """<a class="player" href="{path}/">
      <div class="top"><div class="shield outline" aria-hidden="true">{ini}</div>
        <div><div class="name outline">{name}</div><div class="sub">{tag} · {n} battles</div></div></div>
      <div class="stats">
        <div class="stat"><span class="k">Record</span><span class="v">{w}–{l}</span></div>
        <div class="stat"><span class="k">Win rate</span><span class="v win">{wr}</span></div>
        <div class="stat"><span class="k">Trophies</span><span class="v gold">{tr}</span></div>
      </div>
      <span class="open">Open {name}'s report</span>
    </a>"""


def footer(config):
    return FOOTER.replace("{repo}", config["repo"]).replace("{version}", html.escape(config["version"]))


def landing(config, generated):
    """The site's front page: one button per player, with their headline numbers."""
    players = load_players()
    cards = []
    for p in config["pages"]:
        battles = load_battles(DATA_DIR / p["player"] / "battles.csv")
        w = sum(b["res"] == "W" for b in battles)
        l = sum(b["res"] == "L" for b in battles)
        last = next((b for b in reversed(battles) if b["tr"] is not None), None)
        name = html.escape(p["name"])
        cards.append(CARD.format(
            path=p["path"], name=name, ini=name[:1].upper(), tag=html.escape(players.get(p["player"], "")),
            n=len(battles), w=w, l=l, wr=f"{round(100 * w / (w + l))}%" if w + l else "–",
            tr=f"{last['tr'] + last['dtr']:,}" if last else "–"))
    return (LANDING.read_text(encoding="utf-8")
            .replace("<!--__PLAYERS__-->", "\n    ".join(cards))
            .replace("__GENERATED__", generated)
            .replace("<!--__FOOTER__-->", footer(config)))


def updates_path(player):
    return DATA_DIR / player / "updates.json"


def load_updates(player):
    """Refresh history, oldest first: [{"t": when saved, "battles": [battle times]}]."""
    try:
        return json.loads(updates_path(player).read_text())
    except (FileNotFoundError, ValueError):
        return []


def log_update(player, battle_times):
    """Remember which battles this refresh brought in, for the page's "new battles" popup."""
    log = load_updates(player)
    log.append({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "battles": battle_times})
    updates_path(player).write_text(json.dumps(log[-KEEP_UPDATES:], indent=1) + "\n")


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
            res = collect(name, players[name], token)
            print("  " + summary_line(res))
            status[name] = "ok"
            if res["new"]:
                log_update(name, [r["battle_time_utc"] for r in res["new_battles"]])
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
            "updates": load_updates(p["player"]),
        }
        blob = json.dumps(rr, separators=(",", ":")).replace("</", "<\\/")
        # The template is a page body (no <html>/<head>), so give it a proper document head.
        out.write_text(HEAD.replace("{rr}", blob) + out.read_text(encoding="utf-8") + footer(config),
                       encoding="utf-8")
    (site / "index.html").write_text(landing(config, generated), encoding="utf-8")
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
