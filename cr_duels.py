#!/usr/bin/env python3
"""
Clan Wars duel tracker: the duel version of cr_collect.py.

Duels (riverRaceDuel / riverRaceDuelColosseum) are best-of-3 with a
different deck each round, so they don't fit battles.csv and stay out of
every regular stat and dashboard. This keeps them on their own:

  data/<player>/duels.csv        one row per duel, with each round's decks and crowns
  data/<player>/duels_raw.jsonl  the API's full record of each duel, so the CSV
                                 can be rebuilt if the parsing ever needs fixing
  data/<player>/DUEL_STATS.md    duel and round record, sweeps, recent form, decks

USAGE
  python3 cr_duels.py              # me
  python3 cr_duels.py ryan         # anyone in players.json
  python3 cr_duels.py --rebuild    # re-parse duels_raw.jsonl, no API call

run_all.py and build_site.py also track duels from the same API call they
use for regular battles, so nothing extra needs to run. Standard library only.
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

sys.dont_write_bytecode = True  # keep __pycache__ out of the folder

from cr_collect import (DATA_DIR, DEFAULT_BASE, CollectError, deck_fields, fetch_battlelog,
                        load_players, local_time, parse_time, read_token, record_str,
                        stamp, tower_troop, win_pct)

DUEL_TYPES = {"riverRaceDuel", "riverRaceDuelColosseum"}
MAX_ROUNDS = 3

DUEL_FIELDS = [
    "battle_id", "battle_time_utc", "battle_type", "game_mode",
    "result", "rounds_won", "rounds_lost", "rounds_played", "result_from",
    "my_crowns", "opp_crowns", "my_tower_troop", "my_elixir_leaked",
    "opp_tag", "opp_name", "opp_tower_troop", "opp_elixir_leaked",
]
for _n in range(1, MAX_ROUNDS + 1):
    DUEL_FIELDS += [f"r{_n}_result", f"r{_n}_my_crowns", f"r{_n}_opp_crowns",
                    f"r{_n}_my_deck", f"r{_n}_my_card_levels", f"r{_n}_opp_deck", f"r{_n}_opp_card_levels"]


def paths(name):
    folder = DATA_DIR / name
    return folder, folder / "duels.csv", folder / "duels_raw.jsonl", folder / "DUEL_STATS.md"


def is_duel(battle):
    return battle.get("type") in DUEL_TYPES


def duel_id(battle):
    opp = (battle.get("opponent") or [{}])[0]
    return f"{battle.get('battleTime', '')}_{opp.get('tag', '')}"


def side_rounds(side):
    """
    One entry per round: (crowns or None, cards, elixir leaked). The API lists rounds under
    side["rounds"]. If a record ever comes without them, fall back to splitting the
    side's cards into 8-card decks, with no per-round crowns.
    """
    rounds = side.get("rounds")
    if rounds:
        return [(r.get("crowns"), r.get("cards") or [], r.get("elixirLeaked")) for r in rounds]
    cards = side.get("cards") or []
    return [(None, cards[i:i + 8], None) for i in range(0, len(cards), 8)]


def duel_to_row(battle, my_tag):
    teams = battle.get("team") or []
    opps = battle.get("opponent") or []
    me = next((p for p in teams if p.get("tag") == my_tag), teams[0] if teams else {})
    opp = opps[0] if opps else {}
    mine, theirs = side_rounds(me), side_rounds(opp)

    row = {k: "" for k in DUEL_FIELDS}
    won = lost = 0
    leaked_me = leaked_opp = 0.0
    for n in range(min(MAX_ROUNDS, max(len(mine), len(theirs)))):
        mc, mcards, mleak = mine[n] if n < len(mine) else (None, [], None)
        oc, ocards, oleak = theirs[n] if n < len(theirs) else (None, [], None)
        p = f"r{n + 1}_"
        row[p + "my_deck"], row[p + "my_card_levels"], _ = deck_fields(mcards)
        row[p + "opp_deck"], row[p + "opp_card_levels"], _ = deck_fields(ocards)
        if mc is not None and oc is not None:
            row[p + "my_crowns"], row[p + "opp_crowns"] = mc, oc
            res = "win" if mc > oc else "loss" if mc < oc else "draw"
            row[p + "result"] = res
            won += res == "win"
            lost += res == "loss"
        leaked_me += mleak or 0
        leaked_opp += oleak or 0
    played = max(len(mine), len(theirs))

    my_crowns, opp_crowns = me.get("crowns", 0), opp.get("crowns", 0)
    if won or lost:
        result = "win" if won > lost else "loss" if lost > won else "draw"
        source = "rounds"
    else:
        # No per-round crowns: the side with more total crowns is the best guess.
        result = "win" if my_crowns > opp_crowns else "loss" if my_crowns < opp_crowns else "draw"
        source = "total crowns"

    row.update({
        "battle_id": duel_id(battle),
        "battle_time_utc": parse_time(battle.get("battleTime", "")),
        "battle_type": battle.get("type", ""),
        "game_mode": (battle.get("gameMode") or {}).get("name", ""),
        "result": result, "rounds_won": won if source == "rounds" else "",
        "rounds_lost": lost if source == "rounds" else "", "rounds_played": played,
        "result_from": source,
        "my_crowns": my_crowns, "opp_crowns": opp_crowns,
        "my_tower_troop": tower_troop(me),
        "my_elixir_leaked": round(leaked_me, 2) if leaked_me else me.get("elixirLeaked", ""),
        "opp_tag": opp.get("tag", ""), "opp_name": opp.get("name", ""),
        "opp_tower_troop": tower_troop(opp),
        "opp_elixir_leaked": round(leaked_opp, 2) if leaked_opp else opp.get("elixirLeaked", ""),
    })
    return row


# ---------------------------------------------------------------- files

def load_raw(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_csv(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DUEL_FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def write_stats(path, rows, name, tag):
    def rec(rs):
        w = sum(r["result"] == "win" for r in rs)
        l = sum(r["result"] == "loss" for r in rs)
        d = len(rs) - w - l
        return f"{record_str(w, l, d)} ({win_pct(w, l)}%)" if rs else "–"

    lines = [f"# Duel stats: {name} ({tag})", "",
             "Clan Wars duels only (best of 3). These never count in STATS.md or the dashboard.", ""]
    if not rows:
        lines += ["No duels saved yet."]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    rw = sum(int(r["rounds_won"] or 0) for r in rows)
    rl = sum(int(r["rounds_lost"] or 0) for r in rows)
    sweeps = sum(r["result"] == "win" and r["rounds_lost"] == "0" for r in rows)
    swept = sum(r["result"] == "loss" and r["rounds_won"] == "0" for r in rows)
    lines += [
        f"**Duels:** {rec(rows)} over {len(rows)} duels, "
        f"{local_time(rows[0]['battle_time_utc'])} to {local_time(rows[-1]['battle_time_utc'])}",
        f"**Rounds:** {record_str(rw, rl, 0)} ({win_pct(rw, rl)}%)",
        f"**Sweeps:** won 2-0 {sweeps} times, lost 0-2 {swept} times",
        f"**Last 10 duels:** {rec(rows[-10:])}", "",
        "## Recent duels", "", "| When | Result | Rounds | Opponent |", "|---|---|---|---|",
    ]
    for r in reversed(rows[-10:]):
        rounds = f"{r['rounds_won']}-{r['rounds_lost']}" if r["result_from"] == "rounds" else "?"
        lines.append(f"| {local_time(r['battle_time_utc'])} | {r['result'].upper()} | {rounds} | {r['opp_name']} |")

    # Round win rate per deck, across every round slot it was played in.
    decks = defaultdict(Counter)
    for r in rows:
        for n in range(1, MAX_ROUNDS + 1):
            if r[f"r{n}_my_deck"] and r[f"r{n}_result"]:
                decks[r[f"r{n}_my_deck"]][r[f"r{n}_result"]] += 1
    if decks:
        lines += ["", "## Your duel decks (by round)", "", "| Rounds | Record | Deck |", "|---|---|---|"]
        for deck, c in sorted(decks.items(), key=lambda kv: -sum(kv[1].values()))[:8]:
            lines.append(f"| {sum(c.values())} | {record_str(c['win'], c['loss'], c['draw'])} "
                         f"({win_pct(c['win'], c['loss'])}%) | {deck.replace('|', ', ')} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- collect

def collect_duels(name, tag, battles=None, token=None, base_url=DEFAULT_BASE, rebuild=False):
    """
    Save any new duels for one player. Pass `battles` (an already-fetched battle log)
    to avoid a second API call; otherwise this fetches one with `token`.
    With rebuild=True, re-parse duels_raw.jsonl without calling the API.
    """
    folder, csv_path, raw_path, stats_path = paths(name)
    raw = load_raw(raw_path)
    seen = {duel_id(b) for b in raw}
    added = []
    if not rebuild:
        if battles is None:
            battles = fetch_battlelog(base_url, token, tag)
        for b in battles:
            if is_duel(b) and duel_id(b) not in seen:
                raw.append(b)
                added.append(b)
                seen.add(duel_id(b))
    raw.sort(key=lambda b: b.get("battleTime", ""))
    rows = [duel_to_row(b, tag) for b in raw]

    if raw or csv_path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        if added or rebuild:
            tmp = raw_path.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(json.dumps(b, separators=(",", ":")) + "\n" for b in raw), encoding="utf-8")
            os.replace(tmp, raw_path)
        write_csv(csv_path, rows)
        write_stats(stats_path, rows, name, tag)
    new_rows = [duel_to_row(b, tag) for b in added]
    return {"name": name, "new": len(added), "new_rows": new_rows, "logged": len(rows),
            "w": sum(r["result"] == "win" for r in rows), "l": sum(r["result"] == "loss" for r in rows)}


def duel_summary(res):
    if not res["new"] and not res["logged"]:
        return ""
    nw = sum(r["result"] == "win" for r in res["new_rows"])
    what = f"{res['new']} new ({nw}-{res['new'] - nw})" if res["new"] else "0 new"
    return f"{res['name']:<8} duels {what:<10} {res['logged']:>4} logged   duel record {res['w']}-{res['l']}"


def main():
    ap = argparse.ArgumentParser(description="Track one player's Clan Wars duels separately.")
    ap.add_argument("player", nargs="?", default="me", help="name in players.json (default: me)")
    ap.add_argument("--rebuild", action="store_true", help="re-parse saved duels, no API call")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    args = ap.parse_args()
    try:
        players = load_players()
        name = args.player.lower()
        if name not in players:
            raise CollectError(f"'{args.player}' isn't in players.json")
        token = None if args.rebuild else read_token()
        res = collect_duels(name, players[name], token=token, base_url=args.base_url, rebuild=args.rebuild)
    except CollectError as e:
        sys.exit(f"[{stamp()}] {e}")
    print(f"[{stamp()}] " + (duel_summary(res) or f"{name}: no duels yet"))


if __name__ == "__main__":
    main()
