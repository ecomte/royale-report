#!/usr/bin/env python3
"""
Build an interactive battle dashboard (one HTML page) for one player.

  python3 cr_dashboard.py me --name E     # writes data/me/dashboard.html
  python3 cr_dashboard.py ryan --name Ryan

Reads data/<player>/battles.csv only (never changes it). Clan Wars boat
battles and duels are skipped, same as the stats. The page itself is
dashboard_template.html with the battles dropped in, so tweak the look
there and re-run this script. Standard library only, no API calls.
"""

import argparse
import csv
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the folder

try:
    from cr_collect import EXCLUDED_TYPES
except ImportError:
    EXCLUDED_TYPES = {"boatBattle", "riverRaceDuel", "riverRaceDuelColosseum"}

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "dashboard_template.html"
CARD_ART = HERE / "data" / "card_art.json"   # card images, saved by build_site.py from the API
COUNTERS = HERE / "counters.json"   # card counters from the Clash Royale Wiki, for Card suggestions

# Elixir cost and rarity for the card tiles. Cards missing here still work,
# their tile just has no elixir drop. Add new cards as they come out.
# An empty rarity ("") shows the plain grey border.
CARDS = {
    "Archer Queen": (5, "champion"), "Archers": (3, "common"), "Arrows": (3, "common"),
    "Baby Dragon": (4, "epic"), "Balloon": (5, "epic"), "Bandit": (3, "legendary"),
    "Barbarian Barrel": (2, "epic"), "Barbarians": (5, "common"), "Bats": (2, "common"),
    "Battle Healer": (4, "rare"), "Battle Ram": (4, "rare"), "Berserker": (2, "common"),
    "Bomb Tower": (4, "rare"), "Bomber": (2, "common"), "Bowler": (5, "epic"),
    "Cannon": (3, "common"), "Cannon Cart": (5, "epic"), "Clone": (3, "epic"),
    "Dark Prince": (4, "epic"), "Dart Goblin": (3, "rare"), "Earthquake": (3, "rare"),
    "Electro Dragon": (5, "epic"), "Electro Giant": (7, "epic"), "Electro Spirit": (1, "common"),
    "Electro Wizard": (4, "legendary"), "Elite Barbarians": (6, "common"),
    "Elixir Collector": (6, "rare"), "Elixir Golem": (3, "rare"), "Executioner": (5, "epic"),
    "Fire Spirit": (1, "common"), "Fireball": (4, "rare"), "Firecracker": (3, "common"),
    "Fisherman": (3, "legendary"), "Flying Machine": (4, "rare"), "Freeze": (4, "epic"),
    "Furnace": (4, "rare"), "Giant": (5, "rare"), "Giant Skeleton": (6, "epic"),
    "Giant Snowball": (2, "common"), "Goblin Barrel": (3, "epic"), "Goblin Cage": (4, "rare"),
    "Goblin Curse": (2, "epic"), "Goblin Drill": (4, "epic"), "Goblin Gang": (3, "common"),
    "Goblin Giant": (6, "epic"), "Goblin Hut": (5, "rare"), "Goblins": (2, "common"),
    "Golden Knight": (4, "champion"), "Golem": (8, "epic"), "Graveyard": (5, "legendary"),
    "Guards": (3, "epic"), "Heal Spirit": (1, "rare"), "Hog Rider": (4, "rare"),
    "Hunter": (4, "epic"), "Ice Golem": (2, "rare"), "Ice Spirit": (1, "common"),
    "Ice Wizard": (3, "legendary"), "Inferno Dragon": (4, "legendary"),
    "Inferno Tower": (5, "rare"), "Knight": (3, "common"), "Lava Hound": (7, "legendary"),
    "Lightning": (6, "epic"), "Little Prince": (3, "champion"), "Lumberjack": (4, "legendary"),
    "Magic Archer": (4, "legendary"), "Mega Knight": (7, "legendary"), "Mega Minion": (3, "rare"),
    "Mighty Miner": (4, "champion"), "Miner": (3, "legendary"), "Mini P.E.K.K.A": (4, "rare"),
    "Minion Horde": (5, "common"), "Minions": (3, "common"), "Monk": (5, "champion"),
    "Mortar": (4, "common"), "Mother Witch": (4, "legendary"), "Musketeer": (4, "rare"),
    "Night Witch": (4, "legendary"), "P.E.K.K.A": (7, "epic"), "Phoenix": (4, "legendary"),
    "Poison": (4, "epic"), "Prince": (5, "epic"), "Princess": (3, "legendary"),
    "Rage": (2, "epic"), "Ram Rider": (5, "legendary"), "Rascals": (5, "common"),
    "Rocket": (6, "rare"), "Ronin": (5, ""), "Royal Delivery": (3, "common"), "Royal Ghost": (3, "legendary"),
    "Royal Giant": (6, "common"), "Royal Hogs": (5, "rare"), "Royal Recruits": (7, "common"),
    "Skeleton Army": (3, "epic"), "Skeleton Barrel": (3, "common"),
    "Skeleton Dragons": (4, "common"), "Skeleton King": (4, "champion"), "Skeletons": (1, "common"),
    "Sparky": (6, "legendary"), "Spear Goblins": (2, "common"), "Suspicious Bush": (2, "rare"),
    "Tesla": (4, "common"), "The Log": (2, "legendary"), "Three Musketeers": (9, "rare"),
    "Tombstone": (3, "rare"), "Tornado": (3, "epic"), "Valkyrie": (4, "rare"),
    "Void": (3, "epic"), "Wall Breakers": (2, "epic"), "Witch": (5, "epic"),
    "Wizard": (5, "rare"), "X-Bow": (6, "epic"), "Zap": (2, "common"), "Zappies": (4, "rare"),
}

# Card types for the Card suggestions tab, so a swap idea trades a spell for a
# spell and a building for a building. Everything not listed is a troop.
SPELLS = {
    "Arrows", "Barbarian Barrel", "Clone", "Earthquake", "Fireball", "Freeze", "Giant Snowball",
    "Goblin Barrel", "Goblin Curse", "Graveyard", "Lightning", "Mirror", "Poison", "Rage", "Rocket",
    "Royal Delivery", "The Log", "Tornado", "Vines", "Void", "Zap",
}
BUILDINGS = {
    "Barbarian Hut", "Bomb Tower", "Cannon", "Elixir Collector", "Furnace", "Goblin Cage",
    "Goblin Drill", "Goblin Hut", "Inferno Tower", "Mortar", "Tesla", "Tombstone", "X-Bow",
}


def kind(card):
    return "spell" if card in SPELLS else "building" if card in BUILDINGS else "troop"


# Opponent archetype = the first group whose win condition is in their deck.
# Order matters: a Golem deck with a Lightning is still beatdown.
ARCHETYPES = [
    ("Siege", {"X-Bow", "Mortar"}),
    ("Three Musketeers", {"Three Musketeers"}),
    ("Elixir Golem", {"Elixir Golem"}),
    ("Beatdown", {"Golem", "Electro Giant", "Goblin Giant", "Giant", "Giant Skeleton"}),
    ("Air (Lava/Loon)", {"Lava Hound", "Balloon"}),
    ("Royal Giant", {"Royal Giant"}),
    ("Hog Rider", {"Hog Rider"}),
    ("Royal Hogs", {"Royal Hogs"}),
    ("Log Bait", {"Goblin Barrel"}),
    ("Graveyard", {"Graveyard"}),
    ("Mega Knight", {"Mega Knight"}),
    ("P.E.K.K.A", {"P.E.K.K.A"}),
    ("Bridge Spam", {"Battle Ram", "Ram Rider", "Bandit", "Royal Ghost", "Elite Barbarians",
                     "Prince", "Dark Prince", "Boss Bandit"}),
    ("Miner / Drill", {"Miner", "Goblin Drill", "Wall Breakers", "Skeleton Barrel", "Mighty Miner"}),
]


def base(card):
    return re.sub(r" \(Evo\)$", "", card)


def archetype(deck):
    names = {base(c) for c in deck}
    for label, wincons in ARCHETYPES:
        if names & wincons:
            return label
    return "Other"


def num(raw, cast=float):
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return None


def load_battles(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("battle_type") not in EXCLUDED_TYPES]
    rows.sort(key=lambda r: r["battle_time_utc"])
    out = []
    for r in rows:
        my, opp = r["my_deck"].split("|"), r["opp_deck"].split("|")
        out.append({
            "t": r["battle_time_utc"],
            "mode": r["game_mode"] or r["battle_type"],
            "arena": r["arena"],
            "res": {"win": "W", "loss": "L"}.get(r["result"], "D"),
            "mc": num(r["my_crowns"], int), "oc": num(r["opp_crowns"], int),
            "tr": num(r["my_starting_trophies"], int), "dtr": num(r["my_trophy_change"], int) or 0,
            "my": my, "myLv": [num(x, int) for x in r["my_card_levels"].split("|")],
            "opp": opp, "oppLv": [num(x, int) for x in r["opp_card_levels"].split("|")],
            "oppName": r["opp_name"], "oppTag": r["opp_tag"], "oppTr": num(r["opp_starting_trophies"], int),
            "oppTower": r["opp_tower_troop"],
            "myLeak": num(r["my_elixir_leaked"]), "oppLeak": num(r["opp_elixir_leaked"]),
            "arch": archetype(opp),
        })
    return out


def load_pool(names):
    """Every tracked player's battles, for the Card suggestions tab.

    Returns [{"name", "wr", "games": [[my cards, enemy cards, 1 if won else 0]]}] with Evos
    merged and draws left out. A game between two tracked players is kept only once.
    """
    players = HERE / "players.json"
    tags = json.loads(players.read_text()) if players.exists() else {}
    pool, seen = [], set()
    for player in sorted(tags):
        csv_path = HERE / "data" / player / "battles.csv"
        if not csv_path.exists():
            continue
        games = []
        for b in load_battles(csv_path):
            key = (b["t"], frozenset((tags[player], b["oppTag"])))
            if b["res"] == "D" or key in seen:
                continue
            seen.add(key)
            games.append([sorted({base(c) for c in b["my"]}), sorted({base(c) for c in b["opp"]}),
                          int(b["res"] == "W")])
        if games:
            pool.append({"name": names.get(player, player.title()), "wr": sum(g[2] for g in games) / len(games),
                         "games": games})
    return pool


def main():
    ap = argparse.ArgumentParser(description="Build a player's battle dashboard page.")
    ap.add_argument("player", help="folder name under data/, e.g. me or ryan")
    ap.add_argument("--name", help="name shown on the page (default: the folder name)")
    ap.add_argument("--csv", help="read this CSV instead of data/<player>/battles.csv")
    ap.add_argument("--out", help="write here instead of data/<player>/dashboard.html")
    args = ap.parse_args()

    folder = HERE / "data" / args.player
    csv_path = Path(args.csv) if args.csv else folder / "battles.csv"
    out_path = Path(args.out) if args.out else folder / "dashboard.html"
    if not csv_path.exists():
        sys.exit(f"No battles at {csv_path}. Run cr_collect.py for {args.player} first.")

    tag = ""
    players = HERE / "players.json"
    if players.exists():
        tag = json.loads(players.read_text()).get(args.player, "")

    # Display names for the pooled players come from the site config (Alpha, OmNs_OaTs, ...).
    names = {}
    config = HERE / "config.json"
    if config.exists():
        names = {p["player"]: p["name"] for p in json.loads(config.read_text()).get("pages", [])}
    if args.name:
        names[args.player] = args.name

    battles = load_battles(csv_path)
    pool = load_pool(names)
    used = {base(c) for b in battles for c in b["my"] + b["opp"]}
    used |= {c for p in pool for g in p["games"] for c in g[0] + g[1]}
    counters = json.loads(COUNTERS.read_text()) if COUNTERS.exists() else None
    if counters:
        used |= {c for k, v in counters["cards"].items() for c in [k, *v]}
    art = json.loads(CARD_ART.read_text()) if CARD_ART.exists() else {}
    data = {
        "player": {"name": args.name or args.player.title(), "tag": tag},
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "battles": battles,
        "cards": {c: [*CARDS[c], kind(c)] if c in CARDS else [None, "", kind(c)] for c in sorted(used)},
        "wincons": sorted(set().union(*(w for _, w in ARCHETYPES)) | {"Royal Giant"}),
        "pool": pool,
        "counters": counters,
        "art": {c: v for c, v in art.items() if c in used},
    }
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", blob)
    page = page.replace("__NAME__", html.escape(data["player"]["name"]), 1)
    out_path.write_text(page, encoding="utf-8")
    w = sum(b["res"] == "W" for b in battles)
    print(f"{data['player']['name']}: {len(battles)} battles ({w}W {len(battles) - w}L) -> {out_path}")


if __name__ == "__main__":
    main()
