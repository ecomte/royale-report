#!/usr/bin/env python3
"""
Clash Royale battle collector: the engine behind everything in this folder.

For one player, it pulls their recent battle log from the official API, merges
any new battles into data/<player>/battles.csv, and rewrites
data/<player>/STATS.md with their lifetime record, recent form, and
breakdowns by mode and deck. Standard library only. See README.md.

USAGE
  python3 cr_collect.py              # me
  python3 cr_collect.py ryan         # anyone listed in players.json
  python3 cr_collect.py ryan --stats-only   # rebuild stats, no API call
  python3 run_all.py                 # everyone in players.json at once

Each run prints one summary line per player; "3 new (2-1)" means three new
battles were saved this run, two wins and one loss.

SETTINGS
  players.json          player name -> tag
  .tokens/cr_api_token  API token, shared by every player (or set CR_API_TOKEN)
  EXCLUDED_TYPES        battle types never saved or counted (below)
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAYERS_FILE = HERE / "players.json"
DATA_DIR = HERE / "data"
TOKEN_FILE = HERE / ".tokens" / "cr_api_token"
DEFAULT_BASE = os.environ.get("CR_API_BASE", "https://proxy.royaleapi.dev/v1")

BATTLE_FIELDS = [
    "battle_id",
    "battle_time_utc",
    "battle_type",
    "game_mode",
    "arena",
    "result",
    "my_crowns",
    "opp_crowns",
    "my_starting_trophies",
    "my_trophy_change",
    "my_deck",
    "my_deck_avg_elixir",
    "my_card_levels",
    "my_tower_troop",
    "my_elixir_leaked",
    "opp_tag",
    "opp_name",
    "opp_starting_trophies",
    "opp_deck",
    "opp_card_levels",
    "opp_tower_troop",
    "opp_elixir_leaked",
]

# Battle types that are skipped entirely: never saved, never counted.
# boatBattle = Clan Wars boat attacks and defenses.
# riverRaceDuel / riverRaceDuelColosseum = Clan Wars best-of-3 duels.
EXCLUDED_TYPES = {"boatBattle", "riverRaceDuel", "riverRaceDuelColosseum"}

# Running lifetime record, recomputed every run.
RECORD_FIELDS = [
    "lifetime_wins",
    "lifetime_losses",
    "lifetime_draws",
    "lifetime_win_pct",
    "lifetime_wl_ratio",
]

FIELDS = BATTLE_FIELDS + RECORD_FIELDS


class CollectError(Exception):
    """A problem worth a one-line message rather than a traceback."""


# ---------------------------------------------------------------- settings

def load_players():
    """players.json -> {name: "#TAG"}, in file order."""
    try:
        players = json.loads(PLAYERS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CollectError(f"Missing {PLAYERS_FILE.name}. It maps player names to tags.")
    except json.JSONDecodeError as e:
        raise CollectError(f"{PLAYERS_FILE.name} isn't valid JSON: {e}")
    out = {}
    for name, tag in players.items():
        tag = tag.strip().upper()
        out[name.lower()] = tag if tag.startswith("#") else "#" + tag
    return out


def read_token():
    # GitHub Actions passes the key in as an environment variable (a repo secret).
    token = os.environ.get("CR_API_TOKEN", "").strip()
    if token:
        return token
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise CollectError(f"No API token. Put it in {TOKEN_FILE} (just the token, nothing else).")
    if not token:
        raise CollectError(f"{TOKEN_FILE} is empty. Paste your API token into it.")
    return token


# ---------------------------------------------------------------- API


def fetch_battlelog(base_url, token, tag):
    url = f"{base_url.rstrip('/')}/players/{urllib.parse.quote(tag)}/battlelog"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        hint = ""
        if e.code == 403:
            hint = (" (403 usually means the key's allowed IP doesn't match -- "
                    "whitelist 45.79.218.79 if you're using the proxy)")
        elif e.code == 404:
            hint = (" (404 means no player has that tag -- tags use the digit 0, "
                    "never the letter O)")
        raise CollectError(f"API error {e.code}{hint}: {body}")
    except urllib.error.URLError as e:
        raise CollectError(f"Network error: {e.reason}")


# ---------------------------------------------------------------- parsing

def card_label(card):
    """Card name, with an evo marker when the card was played evolved."""
    name = card.get("name", "?")
    if card.get("evolutionLevel"):
        name += " (Evo)"
    return name


def normalized_level(card):
    """
    The API reports level relative to the card's rarity. Convert to the
    in-game 1-16 scale so levels compare across rarities.
    """
    level = card.get("level")
    max_level = card.get("maxLevel")
    if level is None or max_level is None:
        return ""
    return level + (16 - max_level)


def deck_fields(cards):
    ordered = sorted(cards, key=lambda c: c.get("name", ""))
    names = "|".join(card_label(c) for c in ordered)
    levels = "|".join(str(normalized_level(c)) for c in ordered)
    costs = [c["elixirCost"] for c in cards if isinstance(c.get("elixirCost"), (int, float))]
    avg = round(sum(costs) / len(costs), 2) if costs else ""
    return names, levels, avg


def tower_troop(side):
    support = side.get("supportCards") or []
    return support[0].get("name", "") if support else ""


def parse_time(raw):
    # API format: 20261014T035801.000Z
    try:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError):
        return raw or ""


def battle_to_row(battle, my_tag):
    teams = battle.get("team") or []
    opps = battle.get("opponent") or []
    me = next((p for p in teams if p.get("tag") == my_tag), teams[0] if teams else {})
    opp = opps[0] if opps else {}

    # In 2v2, crowns are shared per side; we record your own deck and the
    # first opponent's (filter on battle_type/game_mode when analyzing).
    my_crowns = me.get("crowns", 0)
    opp_crowns = opp.get("crowns", 0)
    if my_crowns > opp_crowns:
        result = "win"
    elif my_crowns < opp_crowns:
        result = "loss"
    else:
        result = "draw"

    my_deck, my_levels, my_avg = deck_fields(me.get("cards") or [])
    opp_deck, opp_levels, _ = deck_fields(opp.get("cards") or [])

    raw_time = battle.get("battleTime", "")
    return {
        "battle_id": f"{raw_time}_{opp.get('tag', '')}",
        "battle_time_utc": parse_time(raw_time),
        "battle_type": battle.get("type", ""),
        "game_mode": (battle.get("gameMode") or {}).get("name", ""),
        "arena": (battle.get("arena") or {}).get("name", ""),
        "result": result,
        "my_crowns": my_crowns,
        "opp_crowns": opp_crowns,
        "my_starting_trophies": me.get("startingTrophies", ""),
        "my_trophy_change": me.get("trophyChange", ""),
        "my_deck": my_deck,
        "my_deck_avg_elixir": my_avg,
        "my_card_levels": my_levels,
        "my_tower_troop": tower_troop(me),
        "my_elixir_leaked": me.get("elixirLeaked", ""),
        "opp_tag": opp.get("tag", ""),
        "opp_name": opp.get("name", ""),
        "opp_starting_trophies": opp.get("startingTrophies", ""),
        "opp_deck": opp_deck,
        "opp_card_levels": opp_levels,
        "opp_tower_troop": tower_troop(opp),
        "opp_elixir_leaked": opp.get("elixirLeaked", ""),
    }


# ---------------------------------------------------------------- record keeping

def win_pct(w, l):
    return round(100 * w / (w + l), 1) if (w + l) else 0.0


def wl_ratio(w, l):
    return round(w / l, 2) if l else float(w)


def add_running_record(rows):
    """Fill the lifetime_* columns on every row, oldest to newest."""
    w = l = d = 0
    for row in rows:
        if row["result"] == "win":
            w += 1
        elif row["result"] == "loss":
            l += 1
        else:
            d += 1
        row.update({
            "lifetime_wins": w,
            "lifetime_losses": l,
            "lifetime_draws": d,
            "lifetime_win_pct": win_pct(w, l),
            "lifetime_wl_ratio": wl_ratio(w, l),
        })
    return w, l, d


def load_rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: row.get(k, "") for k in BATTLE_FIELDS} for row in csv.DictReader(f)
                if row.get("battle_type") not in EXCLUDED_TYPES]


def write_rows(path, rows):
    # Write to a temp file and swap it in, so a crash mid-write can't
    # corrupt your history.
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


# ---------------------------------------------------------------- STATS.md

def tally(rows):
    c = Counter(r["result"] for r in rows)
    return c["win"], c["loss"], c["draw"]


def record_str(w, l, d):
    s = f"{w}-{l}"
    if d:
        s += f"-{d}"
    return s


def table_row(label, rows):
    w, l, d = tally(rows)
    return (f"| {label} | {w + l + d} | {record_str(w, l, d)} | "
            f"{win_pct(w, l)}% | {wl_ratio(w, l)} |")


def current_streak(rows):
    streak_result, n = None, 0
    for r in reversed(rows):
        if r["result"] == "draw":
            break
        if streak_result is None:
            streak_result = r["result"]
        if r["result"] != streak_result:
            break
        n += 1
    if not n:
        return "none"
    return f"{n} {'win' if streak_result == 'win' else 'loss'}{'' if n == 1 else ('s' if streak_result == 'win' else 'es')}"


def mode_label(row):
    labels = {
        "PvP": "Ladder",
        "pathOfLegend": "Path of Legends",
        "riverRacePvP": "Clan war: duels/battles",
        "riverRaceDuel": "Clan war: duels",
        "riverRaceDuelColosseum": "Clan war: colosseum duels",
        "challenge": "Challenges",
        "tournament": "Tournaments",
        "clanMate": "Clanmate friendlies",
        "friendly": "Friendlies",
        "casual1v1": "Casual 1v1",
        "casual2v2": "Casual 2v2",
    }
    return labels.get(row["battle_type"], row["game_mode"] or row["battle_type"] or "Other")


def local_time(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%b %-d, %Y %-I:%M %p")
    except ValueError:
        return iso


def write_stats(path, rows, name, tag):
    played = rows
    w, l, d = tally(played)
    now = datetime.now(timezone.utc)

    def since(days):
        cutoff = now - timedelta(days=days)
        out = []
        for r in played:
            try:
                if datetime.fromisoformat(r["battle_time_utc"]) >= cutoff:
                    out.append(r)
            except ValueError:
                pass
        return out

    lines = [
        f"# Clash Royale: lifetime stats ({name})",
        "",
        f"Player **{tag}**. Auto-generated by `cr_collect.py`, so don't edit by hand.",
        f"Updated {datetime.now().strftime('%b %-d, %Y %-I:%M %p')}.",
        "",
        f"## Lifetime record: {record_str(w, l, d)}  ({win_pct(w, l)}% wins, {wl_ratio(w, l)} W/L)",
        "",
        f"- **Current streak:** {current_streak(played)}",
        f"- **Battles tracked:** {len(played)}",
    ]
    if played:
        lines.append(f"- **Tracking since:** {local_time(played[0]['battle_time_utc'])}")
    trophies = [r for r in played if r["battle_type"] == "PvP" and r["my_starting_trophies"]]
    if trophies:
        last = trophies[-1]
        try:
            now_tr = int(last["my_starting_trophies"]) + int(last["my_trophy_change"] or 0)
            lines.append(f"- **Trophies (latest ladder game):** {now_tr}")
        except ValueError:
            pass

    header = ["| | Games | W-L | Win % | W/L |", "|---|---:|---:|---:|---:|"]

    lines += ["", "## Recent form", ""] + header
    lines.append(table_row("Last 10 games", played[-10:]))
    lines.append(table_row("Last 25 games", played[-25:]))
    lines.append(table_row("Last 7 days", since(7)))
    lines.append(table_row("Last 30 days", since(30)))
    lines.append(table_row("**Lifetime**", played))

    by_mode = defaultdict(list)
    for r in played:
        by_mode[mode_label(r)].append(r)
    lines += ["", "## By mode", ""] + header
    for label, rs in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
        lines.append(table_row(label, rs))

    by_deck = defaultdict(list)
    for r in played:
        if r["my_deck"] and r["my_deck"].count("|") + 1 == 8:
            by_deck[r["my_deck"]].append(r)
    if by_deck:
        lines += ["", "## By deck", "",
                  "Decks you've used at least 3 times, most-played first.", "",
                  "| Deck | Games | W-L | Win % | W/L |", "|---|---:|---:|---:|---:|"]
        shown = 0
        for deck, rs in sorted(by_deck.items(), key=lambda kv: -len(kv[1])):
            if len(rs) < 3:
                continue
            lines.append(table_row(deck.replace("|", ", "), rs))
            shown += 1
            if shown == 10:
                break
        if not shown:
            lines.append("| _No deck has 3+ games yet._ | | | | |")

    lines += ["", "---", "",
              "W/L = wins ÷ losses. Win % ignores draws. Clan Wars boat battles "
              "and duels are skipped entirely.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- collecting

def collect(name, tag, token=None, stats_only=False, base_url=DEFAULT_BASE):
    """
    Update one player's battles.csv and STATS.md. Returns a summary dict.
    `token` is only needed when stats_only is False.
    """
    folder = DATA_DIR / name
    csv_path = folder / "battles.csv"
    rows = load_rows(csv_path)
    seen = {r["battle_id"] for r in rows}

    fetched = 0
    added = []
    if not stats_only:
        battles = fetch_battlelog(base_url, token, tag)
        fetched = len(battles)
        for b in battles:
            if b.get("type") in EXCLUDED_TYPES:
                continue
            row = battle_to_row(b, tag)
            if row["battle_id"] not in seen:
                rows.append(row)
                added.append(row)
                seen.add(row["battle_id"])

    rows.sort(key=lambda r: r["battle_time_utc"])
    added.sort(key=lambda r: r["battle_time_utc"])
    w, l, d = add_running_record(rows)
    folder.mkdir(parents=True, exist_ok=True)
    write_rows(csv_path, rows)
    write_stats(folder / "STATS.md", rows, name, tag)
    return {"name": name, "tag": tag, "stats_only": stats_only, "fetched": fetched,
            "new": len(added), "new_battles": added, "logged": len(rows),
            "w": w, "l": l, "d": d}


def summary_line(res):
    w, l, d = res["w"], res["l"], res["d"]
    if res["stats_only"]:
        what = "stats rebuilt"
    elif res["new"]:
        what = f"{res['new']} new ({record_str(*tally(res['new_battles']))})"
    else:
        what = "0 new"
    return (f"{res['name']:<8} {what:<16} {res['logged']:>4} logged   "
            f"lifetime {record_str(w, l, d)} ({win_pct(w, l)}%, {wl_ratio(w, l)} W/L)")


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Collect one player's Clash Royale battles and update their stats.")
    ap.add_argument("player", nargs="?", default="me",
                    help="name from players.json (default: me)")
    ap.add_argument("--stats-only", action="store_true",
                    help="rebuild battles.csv totals and STATS.md without calling the API")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    args = ap.parse_args()

    try:
        players = load_players()
        name = args.player.lower()
        if name not in players:
            raise CollectError(f"No player '{args.player}' in {PLAYERS_FILE.name}. "
                               f"Known: {', '.join(players)}")
        token = None if args.stats_only else read_token()
        res = collect(name, players[name], token, args.stats_only, args.base_url)
    except CollectError as e:
        sys.exit(f"[{stamp()}] {args.player}: {e}")
    print(f"[{stamp()}] {summary_line(res)}")


if __name__ == "__main__":
    main()
