#!/usr/bin/env python3
"""
Refresh the hosted Royale Report from the command line, same as tapping Refresh.

  python3 refresh_site.py

Asks the refresh service (the Cloudflare Worker in config.json) to run the GitHub build,
which pulls new battles for everyone, saves them to the battle-data branch and republishes
the site. Waits for it (about a minute), then prints how many new battles each player got.
No token or API key needed. Standard library only.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text())
WORKER = CONFIG["worker"]
OWNER, NAME = CONFIG["repo"].split("/")
SITE = f"https://{OWNER}.github.io/{NAME}/"
ORIGIN = f"https://{OWNER}.github.io"   # the Worker only starts builds for the site's own pages
POLL = 5
GIVE_UP = 6 * 60


def get(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"Origin": ORIGIN, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.read().decode()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("message")
        except ValueError:
            msg = None
        sys.exit(f"Refresh failed: {msg or f'{url} said {e.code}'}")
    except urllib.error.URLError as e:
        sys.exit(f"Refresh failed: couldn't reach {url} ({e.reason})")


def worker(path, method="GET"):
    return json.loads(get(WORKER + path, method))["run"]


def site_generated():
    return json.loads(get(f"{SITE}status.json?v={time.time()}"))["generated"]


def new_battles(page, since):
    """Battles the player's page says arrived in refreshes since `since` (from its window.RR)."""
    html = get(f"{SITE}{page['path']}/?v={time.time()}")
    m = re.search(r"window\.RR = (\{.*?\});</script>", html)
    updates = json.loads(m.group(1)).get("updates", []) if m else []
    return sum(len(u["battles"]) for u in updates if u["t"] >= since)


def main():
    before = site_generated()
    started = time.time()
    print("Starting the build...")
    reply = json.loads(get(WORKER + "/refresh", "POST"))
    run, since = reply["run"], reply["run"]["created_at"]
    if reply.get("recent"):
        print("A build finished in the last 5 minutes, so the site is already fresh.")
        before = None
    while run["status"] != "completed":
        if time.time() - started > GIVE_UP:
            sys.exit("Gave up: the build is taking too long. Check the Actions tab on GitHub.")
        print(f"  {run['status']}... {round(time.time() - started)}s", end="\r", flush=True)
        time.sleep(POLL)
        run = worker(f"/status?run={run['id']}")
    print()
    if run["conclusion"] != "success":
        sys.exit(f"The build {run['conclusion']} on GitHub: https://github.com/{CONFIG['repo']}/actions/runs/{run['id']}")

    if before:
        print("Build done, waiting for the site to update...")
        for _ in range(24):
            if site_generated() != before:
                break
            time.sleep(POLL)
        else:
            print("The site hasn't changed yet. It can take another minute.")

    for page in CONFIG["pages"]:
        n = new_battles(page, since)
        print(f"  {page['name']:<12} {n} new battle{'s' if n != 1 else ''}")
    print(f"Done in {round(time.time() - started)}s: {SITE}")


if __name__ == "__main__":
    main()
