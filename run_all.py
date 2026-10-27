#!/usr/bin/env python3
"""
Collect battles for every player in players.json in one go.

  python3 run_all.py               # fetch new battles for everyone
  python3 run_all.py --stats-only  # rebuild everyone's stats, no API calls

One player failing (bad tag, API hiccup) doesn't stop the rest. The exit
code is non-zero if any player failed, so cron logs make it obvious.
To add someone, add a line to players.json. Nothing else changes.
"""

import argparse
import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the folder

from cr_collect import (DEFAULT_BASE, CollectError, collect, fetch_battlelog, load_players,
                        read_token, stamp, summary_line)
from cr_duels import collect_duels, duel_summary


def main():
    ap = argparse.ArgumentParser(description="Collect battles for everyone in players.json.")
    ap.add_argument("--stats-only", action="store_true",
                    help="rebuild every player's stats without calling the API")
    args = ap.parse_args()

    try:
        players = load_players()
        token = None if args.stats_only else read_token()
    except CollectError as e:
        sys.exit(f"[{stamp()}] {e}")

    print(f"[{stamp()}] {len(players)} players")
    failed = 0
    for name, tag in players.items():
        try:
            battles = None if args.stats_only else fetch_battlelog(DEFAULT_BASE, token, tag)
            print("  " + summary_line(collect(name, tag, token, args.stats_only, battles=battles)))
            # Duels go to their own duels.csv / DUEL_STATS.md (see cr_duels.py).
            line = duel_summary(collect_duels(name, tag, battles=battles, rebuild=args.stats_only))
            if line:
                print("  " + line)
        except CollectError as e:
            failed += 1
            print(f"  {name:<8} FAILED: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
