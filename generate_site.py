"""
Static HTML site generator for TS-Pool rankings and competition results.

Scrapes new competitions incrementally, accumulates data in a local JSON
database, and generates static HTML pages with Tailwind CSS.

Usage:
    python3 generate_site.py 1353              # Add competition and generate site
    python3 generate_site.py 1340 1345 1353    # Add multiple competitions
    python3 generate_site.py --rebuild         # Regenerate site from existing data
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict
from datetime import date
from pathlib import Path

from tspool_scraper import scrape_competition

# ── Config ───────────────────────────────────────────────────────────────────

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "competitions.json"
CONFIG_FILE = DATA_DIR / "config.json"
SITE_DIR = Path("site")
COMP_DIR = SITE_DIR / "competitions"

def points_for_rank(rank: int) -> int:
    if rank == 1:
        return 8
    if rank == 2:
        return 7
    if rank <= 4:
        return 6
    if rank <= 6:
        return 5
    if rank <= 8:
        return 4
    if rank <= 12:
        return 3
    if rank <= 16:
        return 2
    return 0


def slugify(name: str) -> str:
    """'Kevät 2026' -> 'kevat-2026'"""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s.lower().strip())
    return re.sub(r"[-\s]+", "-", s)


# ── Config ────────────────────────────────────────────────────────────────────


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"current_season": "Kevät 2026", "season_start": None, "season_end": None, "seasons": []}


def save_config(config: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Database ─────────────────────────────────────────────────────────────────


def load_db() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"competitions": {}, "last_updated": None}


def save_db(db: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db["last_updated"] = date.today().isoformat()
    DATA_FILE.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Rankings calculation ─────────────────────────────────────────────────────


def calculate_rankings(db: dict) -> list[dict]:
    """Aggregate player stats across all competitions."""
    players: dict[str, dict] = {}

    for comp_id, comp in db["competitions"].items():
        for s in comp["standings"]:
            name = s["player"]
            pts = points_for_rank(s["rank"])

            if name not in players:
                players[name] = {
                    "player": name,
                    "total_points": 0,
                    "competitions": 0,
                    "best_finish": 999,
                    "podiums": {1: 0, 2: 0, 3: 0},
                    "results": [],
                }

            p = players[name]
            p["total_points"] += pts
            p["competitions"] += 1
            p["best_finish"] = min(p["best_finish"], s["rank"])
            if s["rank"] in p["podiums"]:
                p["podiums"][s["rank"]] += 1
            p["results"].append({
                "comp_id": comp_id,
                "comp_name": comp["info"]["name"],
                "comp_date": comp["info"].get("date", ""),
                "rank": s["rank"],
                "points": pts,
            })

    ranked = sorted(
        players.values(),
        key=lambda p: (-p["total_points"], -p["podiums"][1], -p["podiums"][2], -p["podiums"][3], -p["competitions"]),
    )

    for i, p in enumerate(ranked, 1):
        p["rank"] = i
        p["avg_points"] = round(p["total_points"] / p["competitions"], 1) if p["competitions"] else 0

    return ranked


# ── HTML templates ───────────────────────────────────────────────────────────

TAILWIND_HEAD = """\
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="https://cdn.tailwindcss.com"></script>"""


_FI_MONTHS = {
    "tammikuuta": 1, "helmikuuta": 2, "maaliskuuta": 3, "huhtikuuta": 4,
    "toukokuuta": 5, "kesäkuuta": 6, "heinäkuuta": 7, "elokuuta": 8,
    "syyskuuta": 9, "lokakuuta": 10, "marraskuuta": 11, "joulukuuta": 12,
}


def _parse_fi_date(s: str | None) -> str:
    """Parse Finnish date string (e.g. '23. maaliskuuta 2026') into sortable ISO string."""
    if not s:
        return ""
    parts = s.split()
    if len(parts) == 3:
        day = parts[0].rstrip(".")
        month = _FI_MONTHS.get(parts[1].lower())
        year = parts[2]
        if day.isdigit() and month and year.isdigit():
            return f"{year}-{month:02d}-{int(day):02d}"
    return s


def _fmt_date(s: str | None) -> str:
    """Convert YYYY-MM-DD to Finnish DD.MM.YYYY format."""
    if not s:
        return ""
    try:
        y, m, d = s.split("-")
        return f"{int(d)}.{int(m)}.{y}"
    except (ValueError, AttributeError):
        return s or ""


def _html_escape(s: str | None) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_index_html(
    rankings: list[dict],
    db: dict,
    season_name: str = "Kevät 2026",
    archived_seasons: list[dict] | None = None,
    back_to_current: str | None = None,
    season_end: str | None = None,
) -> str:
    """Generate the main rankings page."""
    # Rankings table rows
    ranking_rows = ""
    for p in rankings:
        if p['rank'] <= 4:
            cell_style = "background:#22c55e18"
        elif p['rank'] <= 12:
            cell_style = "background:#3b82f618"
        else:
            cell_style = ""
        ranking_rows += f"""
                <tr class="border-b border-gray-100 hover:bg-gray-50">
                    <td class="py-3 px-2 sm:px-4 font-semibold text-gray-500" style="{cell_style}">{p['rank']}</td>
                    <td class="py-3 px-2 sm:px-4 font-medium text-gray-900" style="{cell_style}">{_html_escape(p['player'])}</td>
                    <td class="py-3 px-2 sm:px-4 text-center font-bold text-indigo-600" style="{cell_style}">{p['total_points']}</td>
                    <td class="py-3 px-2 sm:px-4 text-center text-gray-600 hidden sm:table-cell" style="{cell_style}">{p['competitions']}</td>
                    <td class="py-3 px-2 sm:px-4 text-center text-gray-600 hidden sm:table-cell" style="{cell_style}">{p['avg_points']}</td>
                    <td class="py-3 px-2 sm:px-4 text-center font-medium" style="background:#FFD70033">{p['podiums'][1]}</td>
                    <td class="py-3 px-2 sm:px-4 text-center font-medium" style="background:#C0C0C033">{p['podiums'][2]}</td>
                    <td class="py-3 px-2 sm:px-4 text-center font-medium" style="background:#CD7F3233">{p['podiums'][3]}</td>
                </tr>"""

    # Competition list (sorted latest first by date)
    comps_sorted = sorted(
        db["competitions"].items(),
        key=lambda x: _parse_fi_date(x[1]["info"].get("date")),
        reverse=True,
    )

    comp_list = ""
    for comp_id, comp in comps_sorted:
        info = comp["info"]
        date_str = _fmt_date(info.get("date"))
        name = _html_escape(info.get("name") or f"Competition {comp_id}")
        location = _html_escape(info.get("location") or "")
        player_count = len(comp.get("standings", []))
        comp_list += f"""
                <a href="competitions/{comp_id}.html"
                   class="block p-4 rounded-lg border border-gray-200 hover:border-indigo-300 hover:shadow-md transition-all">
                    <div class="flex justify-between items-start">
                        <div>
                            <h3 class="font-semibold text-gray-900">{name}</h3>
                            <p class="text-sm text-gray-500 mt-1">{date_str}</p>
                            <p class="text-sm text-gray-400">{location}</p>
                        </div>
                        <span class="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full">{player_count} pelaajaa</span>
                    </div>
                </a>"""

    # Navigation for archived pages
    nav_html = ""
    if back_to_current:
        nav_html = f"""
        <nav class="mb-6">
            <a href="{back_to_current}" class="text-indigo-600 hover:text-indigo-800 text-sm">&larr; Nykyinen kausi</a>
        </nav>"""

    # Previous seasons section
    seasons_html = ""
    if archived_seasons:
        season_links = ""
        for s in archived_seasons:
            season_links += f"""
                <a href="seasons/{_html_escape(s['slug'])}/index.html"
                   class="block p-3 rounded-lg border border-gray-200 hover:border-indigo-300 hover:shadow-md transition-all">
                    <span class="font-medium text-gray-900">{_html_escape(s['name'])}</span>
                </a>"""
        seasons_html = f"""
        <section class="mt-10">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Edelliset kaudet</h2>
            <div class="grid gap-3">{season_links}
            </div>
        </section>"""

    escaped_season = _html_escape(season_name)

    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
    {TAILWIND_HEAD}
    <title>Pori Viikkokisa Ranking - {escaped_season}</title>
</head>
<body class="bg-gray-50 min-h-screen">
    <div class="max-w-5xl mx-auto px-4 py-8">{nav_html}
        <header class="mb-8">
            <h1 class="text-2xl sm:text-3xl font-bold text-gray-900">Pori Viikkokisa Ranking - {escaped_season}</h1>
            <p class="text-gray-500 mt-1">Porin Viikkokisat{(" &middot; Kausi päättyy " + _fmt_date(season_end)) if season_end else ""} &middot; Päivitetty {_fmt_date(db.get('last_updated'))}</p>
        </header>

        <section class="mb-10">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Kokonaisranking</h2>
            <div class="bg-white rounded-xl shadow-sm overflow-x-auto">
                <table class="w-full">
                    <thead>
                        <tr class="bg-gray-50 text-left text-sm text-gray-500 uppercase tracking-wider">
                            <th class="py-3 px-2 sm:px-4 w-10">#</th>
                            <th class="py-3 px-2 sm:px-4">Pelaaja</th>
                            <th class="py-3 px-2 sm:px-4 text-center">Pisteet</th>
                            <th class="py-3 px-2 sm:px-4 text-center hidden sm:table-cell">Pelatut Kisat</th>
                            <th class="py-3 px-2 sm:px-4 text-center hidden sm:table-cell">Pistekeskiarvo</th>
                            <th class="py-3 px-2 sm:px-4 text-center" style="background:#FFD700;color:#7a5c00">1.</th>
                            <th class="py-3 px-2 sm:px-4 text-center" style="background:#C0C0C0;color:#4a4a4a">2.</th>
                            <th class="py-3 px-2 sm:px-4 text-center" style="background:#CD7F32;color:#fff">3.</th>
                        </tr>
                    </thead>
                    <tbody>{ranking_rows}
                    </tbody>
                </table>
            </div>
            <div class="flex flex-wrap gap-4 mt-2">
                <p class="text-xs text-gray-400">Pisteet: 1.=8, 2.=7, 3.-4.=6, 5.-6.=5, 7.-8.=4, 9.-12.=3, 13.-16.=2</p>
                <div class="flex gap-3 text-xs text-gray-500">
                    <span class="flex items-center gap-1"><span class="inline-block w-3 h-3 rounded-sm" style="background:#22c55e40"></span> Top 4: Sijoitetaan finaalitapahtuman kaavioon</span>
                    <span class="flex items-center gap-1"><span class="inline-block w-3 h-3 rounded-sm" style="background:#3b82f640"></span> Top 12: Pääsee mukaan kauden finaalitapahtumaan</span>
                </div>
            </div>
        </section>

        <section>
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Kilpailut</h2>
            <div class="grid gap-3">{comp_list}
            </div>
        </section>{seasons_html}
    </div>
</body>
</html>"""


def generate_competition_html(comp_id: str, comp: dict, rankings: list[dict]) -> str:
    """Generate a detail page for a single competition."""
    info = comp["info"]
    name = _html_escape(info.get("name") or f"Competition {comp_id}")
    date_str = _fmt_date(info.get("date"))
    time_str = _html_escape(info.get("time") or "")
    location = _html_escape(info.get("location") or "")
    game_type = _html_escape(info.get("game_type") or "")
    details = _html_escape(info.get("details") or "")

    # Standings with points
    standings_rows = ""
    for s in comp.get("standings", []):
        pts = points_for_rank(s["rank"])
        standings_rows += f"""
                <tr class="border-b border-gray-100">
                    <td class="py-2 px-4 font-semibold text-gray-500">{s['rank']}</td>
                    <td class="py-2 px-4 text-gray-900">{_html_escape(s['player'])}</td>
                    <td class="py-2 px-4 text-center font-medium text-indigo-600">+{pts}</td>
                </tr>"""

    # Match results grouped by round
    matches_html = ""
    current_round = ""
    for m in comp.get("matches", []):
        if m["round_name"] != current_round:
            current_round = m["round_name"]
            matches_html += f"""
                <tr class="bg-gray-50">
                    <td colspan="6" class="py-2 px-2 sm:px-4 font-semibold text-gray-700 text-sm">{_html_escape(current_round)} (race to {m['race_to']})</td>
                </tr>"""

        home_cls = "font-semibold" if m.get("winner") == m["home_player"] else ""
        away_cls = "font-semibold" if m.get("winner") == m["away_player"] else ""
        home_score_cls = "font-bold text-green-600" if m.get("winner") == m["home_player"] else "text-gray-500"
        away_score_cls = "font-bold text-green-600" if m.get("winner") == m["away_player"] else "text-gray-500"
        table_num = m.get("table_number") or ""
        duration = _html_escape(m.get("duration") or "")

        matches_html += f"""
                <tr class="border-b border-gray-100 hover:bg-gray-50">
                    <td class="py-2 px-2 sm:px-4 text-gray-400 text-sm hidden sm:table-cell">#{m['match_number']}</td>
                    <td class="py-2 px-2 sm:px-4 text-right {home_cls}">{_html_escape(m['home_player'])}</td>
                    <td class="py-2 px-2 text-center whitespace-nowrap">
                        <span class="{home_score_cls}">{m['home_score']}</span>
                        <span class="text-gray-400 mx-1">-</span>
                        <span class="{away_score_cls}">{m['away_score']}</span>
                    </td>
                    <td class="py-2 px-2 sm:px-4 {away_cls}">{_html_escape(m['away_player'])}</td>
                    <td class="py-2 px-2 sm:px-4 text-center text-gray-400 text-sm hidden sm:table-cell">{table_num}</td>
                    <td class="py-2 px-2 sm:px-4 text-center text-gray-400 text-sm hidden sm:table-cell">{duration}</td>
                </tr>"""

    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
    {TAILWIND_HEAD}
    <title>{name} - TS-Pool</title>
</head>
<body class="bg-gray-50 min-h-screen">
    <div class="max-w-5xl mx-auto px-4 py-8">
        <nav class="mb-6">
            <a href="../index.html" class="text-indigo-600 hover:text-indigo-800 text-sm">&larr; Takaisin rankingiin</a>
        </nav>

        <header class="mb-8">
            <h1 class="text-2xl sm:text-3xl font-bold text-gray-900">{name}</h1>
            <div class="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-gray-500">
                {"<span>" + date_str + "</span>" if date_str else ""}
                {"<span>" + time_str + "</span>" if time_str else ""}
                {"<span>" + location + "</span>" if location else ""}
                {"<span>Peli: " + game_type + "-ball</span>" if game_type else ""}
            </div>
            {"<p class='mt-2 text-sm text-gray-400'>" + details + "</p>" if details else ""}
        </header>

        <section class="mb-10">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Lopputulokset</h2>
            <div class="bg-white rounded-xl shadow-sm overflow-hidden">
                <table class="w-full">
                    <thead>
                        <tr class="bg-gray-50 text-left text-sm text-gray-500 uppercase tracking-wider">
                            <th class="py-2 px-4 w-12">#</th>
                            <th class="py-2 px-4">Pelaaja</th>
                            <th class="py-2 px-4 text-center">Pisteet</th>
                        </tr>
                    </thead>
                    <tbody>{standings_rows}
                    </tbody>
                </table>
            </div>
        </section>

        <section>
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Ottelutulokset</h2>
            <div class="bg-white rounded-xl shadow-sm overflow-x-auto">
                <table class="w-full">
                    <thead>
                        <tr class="bg-gray-50 text-left text-sm text-gray-500 uppercase tracking-wider">
                            <th class="py-2 px-2 sm:px-4 w-8 hidden sm:table-cell"></th>
                            <th class="py-2 px-2 sm:px-4 text-right">Koti</th>
                            <th class="py-2 px-2 text-center w-20">Tulos</th>
                            <th class="py-2 px-2 sm:px-4">Vieras</th>
                            <th class="py-2 px-2 sm:px-4 text-center w-16 hidden sm:table-cell">Pöytä</th>
                            <th class="py-2 px-2 sm:px-4 text-center w-16 hidden sm:table-cell">Aika</th>
                        </tr>
                    </thead>
                    <tbody>{matches_html}
                    </tbody>
                </table>
            </div>
        </section>
    </div>
</body>
</html>"""


# ── Site generation ──────────────────────────────────────────────────────────


def generate_site(db: dict) -> None:
    """Generate all static HTML files from the database."""
    config = load_config()
    season_name = config["current_season"]
    archived_seasons = config.get("seasons", [])

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    COMP_DIR.mkdir(parents=True, exist_ok=True)

    rankings = calculate_rankings(db)

    # Main rankings page
    index_html = generate_index_html(
        rankings, db, season_name, archived_seasons=archived_seasons,
        season_end=config.get("season_end"),
    )
    (SITE_DIR / "index.html").write_text(index_html, encoding="utf-8")

    # Per-competition pages
    for comp_id, comp in db["competitions"].items():
        comp_html = generate_competition_html(comp_id, comp, rankings)
        (COMP_DIR / f"{comp_id}.html").write_text(comp_html, encoding="utf-8")

    # Regenerate archived season sites
    for season in archived_seasons:
        slug = season["slug"]
        season_data_file = DATA_DIR / "seasons" / slug / "competitions.json"
        if not season_data_file.exists():
            continue

        season_db = json.loads(season_data_file.read_text(encoding="utf-8"))
        season_site_dir = SITE_DIR / "seasons" / slug
        season_comp_dir = season_site_dir / "competitions"
        season_site_dir.mkdir(parents=True, exist_ok=True)
        season_comp_dir.mkdir(parents=True, exist_ok=True)

        season_rankings = calculate_rankings(season_db)
        season_index = generate_index_html(
            season_rankings, season_db, season["name"],
            back_to_current="../../index.html",
        )
        (season_site_dir / "index.html").write_text(season_index, encoding="utf-8")

        for comp_id, comp in season_db["competitions"].items():
            comp_html = generate_competition_html(comp_id, comp, season_rankings)
            (season_comp_dir / f"{comp_id}.html").write_text(comp_html, encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate TS-Pool rankings site")
    parser.add_argument("competition_ids", nargs="*", type=int,
                        help="Competition ID(s) to scrape and add")
    parser.add_argument("--rebuild", action="store_true",
                        help="Regenerate site from existing data without scraping")
    args = parser.parse_args()

    if not args.competition_ids and not args.rebuild:
        parser.error("Provide competition ID(s) or use --rebuild")

    db = load_db()

    for comp_id in args.competition_ids:
        if str(comp_id) in db["competitions"]:
            print(f"Competition {comp_id} already in database, skipping scrape")
            continue

        print(f"Scraping competition {comp_id}...")
        result = scrape_competition(comp_id)
        db["competitions"][str(comp_id)] = {
            "info": asdict(result.info),
            "matches": [asdict(m) for m in result.matches],
            "standings": [asdict(s) for s in result.standings],
        }
        print(f"  Added: {result.info.name} ({len(result.standings)} players, {len(result.matches)} matches)")

    save_db(db)

    print("Generating site...")
    generate_site(db)

    rankings = calculate_rankings(db)
    print(f"\nSite generated in {SITE_DIR}/")
    print(f"  Rankings: {len(rankings)} players across {len(db['competitions'])} competitions")
    print(f"  Open {SITE_DIR / 'index.html'} to view")


if __name__ == "__main__":
    main()
