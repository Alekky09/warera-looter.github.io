import requests
import os
from datetime import datetime
from html import escape


API_BASE = "https://api2.warera.io/trpc"

API_TOKEN = os.environ.get("API_TOKEN")
if not API_TOKEN:
    raise ValueError("API key missing from environment variables.")

HEADERS = {
    "X-API-Key": API_TOKEN,
    "accept": "*/*",
    "Content-Type": "application/json",
}
WEAPONS = {
    "jet": 6,
    "tank": 5,
    "sniper": 4,
    "rifle": 3,
    "gun": 2,
}
THRESHOLDS = {
    2: 'green',
    3: 'blue',
    4: 'purple',
    5: 'gold',
    6: 'red',
}
countries = {}
regions = {}
battles = {}

from datetime import datetime

battle_reports = []

COLORS = {
    "red": "#dc2626",
    "gold": "#eab308",
    "purple": "#9333ea",
    "blue": "#2563eb",
    "green": "#16a34a",
}


def get_all_countries():
    global countries
    r = requests.post(
        f"{API_BASE}/country.getAllCountries",
        headers=HEADERS,
        timeout=30
    )
    r.raise_for_status()
    countries_info = r.json()['result']['data']
    countries = {x['_id']: x['name'] for x in countries_info}


def get_all_regions():
    global regions
    r = requests.post(
        f"{API_BASE}/region.getRegionsObject",
        headers=HEADERS,
        timeout=30
    )
    r.raise_for_status()
    regions_info = r.json()['result']['data']
    regions = {x: regions_info[x]['name'] for x in regions_info}


def get_all_battles():
    global battles
    payload = {
        "isActive": True,
        "limit": 100,
        "direction": "forward",
        "filter": "all",
    }
    while True:
        r = requests.post(
            f"{API_BASE}/battle.getBattles",
            headers=HEADERS,
            json=payload,
            timeout=30
        )
        r.raise_for_status()
        r = r.json()
        battles_info = r['result']['data']['items']
        for battle in battles_info:
            # Skip tournaments
            if battle['type'] == 'tournament':
                continue
            battle_id = battle['_id']
            region = regions[battle['defender']['region']]
            defender_country = countries[battle['defender']['country']]
            defender_damages = battle['currentRound']['defender']['damages'] or 0
            defender_points = battle['currentRound']['defender']['points'] or 0
            attacker_country = countries[battle['attacker']['country']]
            attacker_damages = battle['currentRound']['attacker']['damages'] or 0
            attacker_points = battle['currentRound']['attacker']['points'] or 0
            current_round_id = battle['currentRound']['_id']
            round_number = len(battle['rounds']) + 1
            get_loot_threshold(
                battle_id=battle_id,
                round_id=current_round_id,
                region=region,
                defender_country=defender_country,
                defender_damages=defender_damages,
                defender_points=defender_points,
                attacker_country=attacker_country,
                attacker_damages=attacker_damages,
                attacker_points=attacker_points,
                round_number=round_number,
            )
        if next_cursor := r['result']['data'].get('nextCursor'):
            payload['cursor'] = next_cursor
        else:
            break


def get_loot_threshold(
    battle_id: str,
    round_id: str,
    region: str,
    defender_country: str,
    defender_damages: int,
    defender_points: int,
    attacker_country: str,
    attacker_damages: int,
    attacker_points: int,
    round_number: int,
):
    payload = {
        "roundId": round_id,
        "dataType": "damage",
        "type": "user",
        "side": "merged",
        "limit": 100,
    }

    thresholds = {}
    threshold_damage = 0
    participants = 0
    last_rank = 0

    # Get round loot distribution
    while True:
        r = requests.post(
            f"{API_BASE}/battleRanking.getRanking",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )

        res = r.json()["result"]["data"]
        participants = res["itemCount"]
        warriors = res["items"]

        if not warriors:
            break

        for w in warriors:
            if not w.get("lootItem"):
                break

            threshold_damage = w["value"]
            last_rank = w["rank"]

            code = w["lootItem"]["code"]
            tier = WEAPONS.get(code) if code in WEAPONS else int(code[-1:])
            thresholds[THRESHOLDS[tier]] = threshold_damage

        if threshold_damage != warriors[-1]["value"] or not res.get("nextCursor"):
            break

        payload["cursor"] = res["nextCursor"]

    payload = {
        "battleId": battle_id,
        "dataType": "damage",
        "type": "user",
        "side": "merged",
        "limit": 100,
    }
    overall_thresholds = {}
    overall_threshold_damage = 0
    # Get overall battle loot distribution
    while True:
        r = requests.post(
            f"{API_BASE}/battleRanking.getRanking",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )

        res = r.json()["result"]["data"]
        participants = res["itemCount"]
        warriors = res["items"]

        if not warriors:
            break

        for w in warriors:
            if not w.get("lootItem"):
                break

            overall_threshold_damage = w["value"]

            code = w["lootItem"]["code"]
            tier = WEAPONS.get(code) if code in WEAPONS else int(code[-1:])
            overall_thresholds[THRESHOLDS[tier]] = overall_threshold_damage

        if overall_threshold_damage != warriors[-1]["value"] or not res.get("nextCursor"):
            break

        payload["cursor"] = res["nextCursor"]

    battle_reports.append({
        "region": region,
        "attacker": attacker_country,
        "defender": defender_country,
        "participants": participants,
        "rank": last_rank,
        "need": threshold_damage + 1,
        "thresholds": thresholds,
        "defender_damages": defender_damages,
        "defender_points": defender_points,
        "attacker_damages": attacker_damages,
        "attacker_points": attacker_points,
        "overall_thresholds": overall_thresholds,
        "round_number": round_number,
    })


def generate_html():
    def compact_number(value):
        value = float(value)
        abs_value = abs(value)

        if abs_value >= 1_000_000_000:
            result = f"{value / 1_000_000_000:.1f}B"
        elif abs_value >= 1_000_000:
            result = f"{value / 1_000_000:.1f}M"
        elif abs_value >= 1_000:
            result = f"{value / 1_000:.1f}K"
        else:
            return f"{int(value):,}"

        return result.replace(".0B", "B").replace(".0M", "M").replace(".0K", "K")

    # Order battles by lowest GREEN threshold first
    battle_reports.sort(
        key=lambda b: b["thresholds"].get("green", float("inf"))
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WarEra Battle Report</title>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {{
    --bg-base: #020617;
    --card-bg: rgba(15, 23, 42, 0.6);
    --card-border: rgba(255, 255, 255, 0.06);
    --card-hover: rgba(255, 255, 255, 0.12);
    
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
    --text-dark: #475569;

    --defender: #3b82f6;
    --defender-light: #93c5fd;
    --attacker: #ef4444;
    --attacker-light: #fca5a5;
}}

* {{ box-sizing: border-box; }}

body {{
    margin: 0;
    padding: 40px 24px;
    min-height: 100vh;
    background-color: var(--bg-base);
    background-image: 
        radial-gradient(circle at 15% 50%, rgba(59, 130, 246, 0.04), transparent 25%),
        radial-gradient(circle at 85% 30%, rgba(239, 68, 68, 0.04), transparent 25%);
    background-attachment: fixed;
    color: var(--text-main);
    font-family: 'Inter', sans-serif;
    -webkit-font-smoothing: antialiased;
}}

.header-container {{
    text-align: center;
    margin-bottom: 48px;
}}

h1 {{
    margin: 0;
    font-size: 36px;
    font-weight: 800;
    letter-spacing: -1px;
    background: linear-gradient(135deg, #f8fafc 0%, #94a3b8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}}

.subtitle {{
    color: var(--text-muted);
    margin-top: 8px;
    font-size: 13px;
    font-weight: 500;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 12px;
}}

.badge-tag {{
    background: rgba(255, 255, 255, 0.05);
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}}

.battle-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 24px;
    max-width: 1400px;
    margin: 0 auto;
}}

.card {{
    position: relative;
    padding: 24px;
    border-radius: 20px;
    background: var(--card-bg);
    backdrop-filter: blur(16px);
    border: 1px solid var(--card-border);
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}}

.card:hover {{
    transform: translateY(-4px);
    border-color: var(--card-hover);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255,255,255,0.05);
}}

.card-header {{
    text-align: center;
    margin-bottom: 20px;
}}

.card h3 {{
    margin: 0 0 6px 0;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.5px;
}}

.region-meta {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

.region-meta span.dot {{
    width: 4px; height: 4px;
    background: var(--text-dark);
    border-radius: 50%;
}}

/* ---------------------------------------------------------
   Battle Stats
   --------------------------------------------------------- */
.side-labels {{
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
}}

.side-label {{
    display: flex;
    flex-direction: column;
    font-size: 13px;
    font-weight: 700;
}}

.side-label.defender {{ color: var(--defender-light); align-items: flex-start; }}
.side-label.attacker {{ color: var(--attacker-light); align-items: flex-end; }}

.points-count {{
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 600;
    margin-top: 2px;
}}

/* Slimmed down Points Progress */
.points-bar {{
    position: relative;
    display: flex;
    width: 100%;
    height: 6px;
    border-radius: 999px;
    background: #0f172a;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.5);
    margin-bottom: 16px;
}}

.points-side {{
    position: relative;
    width: 50%;
    height: 100%;
}}

.points-fill {{
    position: absolute;
    top: 0;
    height: 100%;
    border-radius: 999px;
}}

.points-fill.defender {{
    right: 0; /* Grow towards center from left half */
    background: linear-gradient(90deg, #1d4ed8, #60a5fa);
    box-shadow: 0 0 8px rgba(59, 130, 246, 0.4);
}}

.points-fill.attacker {{
    left: 0; /* Grow towards center from right half */
    background: linear-gradient(270deg, #b91c1c, #f87171);
    box-shadow: 0 0 8px rgba(239, 68, 68, 0.4);
}}

.points-center {{
    position: absolute;
    top: -3px;
    left: 50%;
    z-index: 3;
    width: 2px;
    height: 12px;
    transform: translateX(-50%);
    background: #fff;
    border-radius: 2px;
    box-shadow: 0 0 8px rgba(255,255,255,0.6);
}}

/* Refined Damage Bar */
.damage-bar {{
    display: flex;
    width: 100%;
    height: 20px;
    border-radius: 6px;
    background: #0f172a;
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.6);
    overflow: hidden;
}}

.damage-segment {{
    display: flex;
    align-items: center;
    padding: 0 10px;
    font-size: 11px;
    font-weight: 700;
    color: white;
    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
    white-space: nowrap;
    overflow: hidden;
}}

.damage-segment.defender {{
    justify-content: flex-start;
    background: linear-gradient(90deg, #1e3a8a, #2563eb);
    border-right: 1px solid rgba(0,0,0,0.3);
}}

.damage-segment.attacker {{
    justify-content: flex-end;
    background: linear-gradient(270deg, #7f1d1d, #dc2626);
    border-left: 1px solid rgba(255,255,255,0.1);
}}

/* ---------------------------------------------------------
   Threshold Section (Inset style)
   --------------------------------------------------------- */
.thresholds-container {{
    margin-top: 24px;
    padding: 16px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.03);
}}

.threshold-title {{
    font-size: 10px;
    font-weight: 700;
    color: var(--text-dark);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}}
.threshold-title::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(255,255,255,0.05);
}}

.threshold-title:not(:first-child) {{
    margin-top: 20px;
}}

.threshold-row {{
    position: relative;
    width: 100%;
    height: 10px; /* Slimmer */
    margin: 10px 0;
}}

.threshold-track {{
    position: absolute;
    inset: 0;
    border-radius: 999px;
    background: #0f172a;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.8);
}}

.threshold-fill {{
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    border-radius: 999px;
}}

.threshold-fill.red {{ background: linear-gradient(90deg, #991b1b, #f87171); box-shadow: 0 0 8px rgba(239,68,68,0.3); }}
.threshold-fill.gold {{ background: linear-gradient(90deg, #a16207, #fde047); box-shadow: 0 0 8px rgba(234,179,8,0.3); }}
.threshold-fill.purple {{ background: linear-gradient(90deg, #6b21a8, #c084fc); box-shadow: 0 0 8px rgba(168,85,247,0.3); }}
.threshold-fill.blue {{ background: linear-gradient(90deg, #1e40af, #60a5fa); box-shadow: 0 0 8px rgba(59,130,246,0.3); }}
.threshold-fill.green {{ background: linear-gradient(90deg, #166534, #4ade80); box-shadow: 0 0 8px rgba(34,197,94,0.3); }}

.threshold-number {{
    position: absolute;
    top: 50%;
    right: 0;
    transform: translateY(-50%) translateX(20%); /* Slight overhang */
    z-index: 5;
    background: #1e293b;
    border: 1px solid rgba(255,255,255,0.1);
    color: #f8fafc;
    font-size: 10px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.5);
}}

.footer {{
    margin-top: 48px;
    text-align: center;
    color: var(--text-dark);
    font-size: 12px;
    font-weight: 500;
}}
</style>
</head>

<body>

<div class="header-container">
    <h1>WarEra Battle Report</h1>
    <div class="subtitle">
        <span>Generated {datetime.now():%Y-%m-%d %H:%M}</span>
        <span class="badge-tag">Ordered by lowest GREEN threshold</span>
    </div>
</div>

<div class="battle-grid">
"""

    def generate_threshold_bars_html(thresholds_dict, title):
        if not thresholds_dict:
            return ""
            
        t_html = f'<div class="threshold-title">{title}</div>\n'
        max_dmg = max(thresholds_dict.values(), default=1)
        
        for color, dmg in sorted(thresholds_dict.items(), key=lambda x: x[1], reverse=True):
            width = min((dmg / max_dmg) * 100, 100)
            t_html += f"""
        <div class="threshold-row" title="{compact_number(dmg)}">
            <div class="threshold-track">
                <div class="threshold-fill {color}" style="width:{width:.1f}%"></div>
            </div>
            <span class="threshold-number">{compact_number(dmg)}</span>
        </div>
"""
        return t_html

    for battle in battle_reports:
        attacker = escape(str(battle["attacker"]))
        defender = escape(str(battle["defender"]))
        region = escape(str(battle["region"]))
        round_num = battle.get("round_number", 1)

        defender_damage = battle.get("defender_damages", 0) or 0
        attacker_damage = battle.get("attacker_damages", 0) or 0
        defender_points = battle.get("defender_points", 0) or 0
        attacker_points = battle.get("attacker_points", 0) or 0

        total_damage = defender_damage + attacker_damage

        if total_damage > 0:
            defender_damage_pct = (defender_damage / total_damage) * 100
            attacker_damage_pct = (attacker_damage / total_damage) * 100
        else:
            defender_damage_pct = 50
            attacker_damage_pct = 50

        points_goal = 300
        defender_points_pct = min(max((defender_points / points_goal) * 100, 0), 100)
        attacker_points_pct = min(max((attacker_points / points_goal) * 100, 0), 100)

        defender_damage_display = compact_number(defender_damage)
        attacker_damage_display = compact_number(attacker_damage)

        html += f"""
<div class="card">

    <div class="card-header">
        <h3>{region}</h3>
        <div class="region-meta">
            ROUND {round_num} <span class="dot"></span> {battle['participants']:,} PLAYERS
        </div>
    </div>

    <!-- Country labels -->
    <div class="side-labels">
        <div class="side-label defender">
            {defender}
            <span class="points-count">{defender_points:,} / {points_goal} PTS</span>
        </div>
        <div class="side-label attacker">
            {attacker}
            <span class="points-count">{attacker_points:,} / {points_goal} PTS</span>
        </div>
    </div>

    <!-- Points progress -->
    <div class="points-bar">
        <div class="points-side">
            <div class="points-fill defender" style="width:{defender_points_pct:.1f}%; right: 0; left: auto;" title="{defender}: {defender_points:,}"></div>
        </div>
        <div class="points-side">
            <div class="points-fill attacker" style="width:{attacker_points_pct:.1f}%; left: 0; right: auto;" title="{attacker}: {attacker_points:,}"></div>
        </div>
        <div class="points-center"></div>
    </div>

    <!-- Damage -->
    <div class="damage-bar" title="{defender}: {defender_damage_display} • {attacker}: {attacker_damage_display}">
        <div class="damage-segment defender" style="width:{defender_damage_pct:.1f}%">
            <span>{defender_damage_display}</span>
        </div>
        <div class="damage-segment attacker" style="width:{attacker_damage_pct:.1f}%">
            <span>{attacker_damage_display}</span>
        </div>
    </div>

    <!-- Thresholds Inset -->
    <div class="thresholds-container">
"""
        html += generate_threshold_bars_html(battle["thresholds"], f"Round {round_num} Loot")
        
        if battle.get("overall_thresholds"):
            html += generate_threshold_bars_html(battle["overall_thresholds"], "Overall Battle Loot")

        html += """
    </div>
</div>
"""

    html += f"""
</div>

<div class="footer">
    {len(battle_reports)} active battles being tracked
</div>

</body>
</html>
"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("Saved index.html")


get_all_countries()
get_all_regions()
get_all_battles()
generate_html()