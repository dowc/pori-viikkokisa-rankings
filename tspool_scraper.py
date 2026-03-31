"""
TS-Pool single competition result scraper.

Extracts competition metadata, match results, and final standings
from tspool.fi for a given competition ID.

Usage:
    python tspool_scraper.py 1353
    python tspool_scraper.py 1353 --format csv
    python tspool_scraper.py 1353 --output results/
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://tspool.fi"


# ── Data models ──────────────────────────────────────────────────────────────


@dataclass
class Match:
    match_id: int
    match_number: int
    round_name: str
    race_to: int
    home_player: str
    home_score: int
    away_player: str
    away_score: int
    winner: str
    table_number: int | None
    duration: str | None
    status: str  # "ended", "scheduled", etc.


@dataclass
class Standing:
    rank: int
    player: str


@dataclass
class CompetitionInfo:
    competition_id: int
    name: str
    date: str | None
    time: str | None
    location: str | None
    game_type: str | None
    entry_fee: str | None
    max_players: int | None
    details: str | None
    organizers: list[str] = field(default_factory=list)
    players: list[str] = field(default_factory=list)


@dataclass
class CompetitionResult:
    info: CompetitionInfo
    matches: list[Match]
    standings: list[Standing]


# ── Parsing helpers ──────────────────────────────────────────────────────────


def _text(el: Tag | None) -> str:
    """Get cleaned text from a BeautifulSoup element."""
    return el.get_text(strip=True) if el else ""


def _parse_info_field(soup: BeautifulSoup, label: str) -> str | None:
    """Extract a field value from the info page by its bold label."""
    span = soup.find("span", class_="fw-bold", string=re.compile(rf"^\s*{label}\s*$"))
    if not span:
        return None
    # The value follows the span as next sibling text or element
    parent = span.parent
    if not parent:
        return None
    text = parent.get_text()
    # Extract text after the label and colon, up to next label or end
    match = re.search(rf"{label}\s*:\s*(.+?)(?:\n|$)", text, re.DOTALL)
    return match.group(1).strip() if match else None


# ── Scraper functions ────────────────────────────────────────────────────────


def fetch_page(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def scrape_listing(name_filter: str = "Viikkokisat Pori", stop_at_id: int = 0, max_pages: int = 10) -> list[tuple[int, str]]:
    """Scrape the menneet listing and return (comp_id, name) pairs matching name_filter.

    Stops as soon as it encounters a competition ID <= stop_at_id (listings are newest-first).
    """
    results = []
    url = f"{BASE_URL}/kisat/menneet/"

    for _ in range(max_pages):
        soup = fetch_page(url)
        done = False
        for a in soup.find_all("a", href=re.compile(r"^/kisa/\d+/$")):
            m = re.search(r"/kisa/(\d+)/$", a["href"])
            if not m:
                continue
            comp_id = int(m.group(1))
            if stop_at_id and comp_id <= stop_at_id:
                done = True
                break
            text = a.get_text(strip=True)
            name = text.split(" - ", 1)[-1] if " - " in text else text
            if name_filter.lower() in name.lower():
                results.append((comp_id, name))

        if done:
            break
        next_link = soup.find("a", string=re.compile(r"Seuraava"))
        if not next_link:
            break
        url = BASE_URL + next_link["href"]

    return results


def scrape_info(comp_id: int) -> CompetitionInfo:
    """Scrape competition metadata from the info page."""
    soup = fetch_page(f"{BASE_URL}/kisa/{comp_id}/")

    name = _text(soup.find("h1")) or f"Competition {comp_id}"

    # Parse key-value fields from the info paragraph
    info_p = soup.find("p")
    raw_text = info_p.get_text("\n") if info_p else ""

    def extract(label: str) -> str | None:
        m = re.search(rf"{label}\s*:\s*(.+)", raw_text)
        return m.group(1).strip() if m else None

    date = extract("Päivä")
    time = extract("Alkamisaika")
    location = extract("Paikka")
    game_type = extract("Laji")
    entry_fee = extract("Osallistumismaksu")
    max_str = extract("Max osallistujamäärä")
    max_players = int(max_str) if max_str and max_str.isdigit() else None

    # Additional details
    details_span = soup.find("span", class_="fw-bold", string=re.compile("Lisätiedot"))
    details = None
    if details_span and details_span.parent:
        details_el = details_span.find_next_sibling()
        if details_el:
            details = _text(details_el)

    # Organizers
    organizers_label = soup.find("span", class_="fw-bold", string=re.compile("Kisaa vetää"))
    organizers = []
    if organizers_label:
        ul = organizers_label.find_next("ul")
        if ul:
            organizers = [_text(li) for li in ul.find_all("li")]

    # Registered players from the table
    players = []
    players_table = soup.find("table", class_="table-striped")
    if players_table:
        for row in players_table.find("tbody").find_all("tr"):
            cells = row.find_all("td")
            if cells:
                players.append(_text(cells[0]))

    return CompetitionInfo(
        competition_id=comp_id,
        name=name,
        date=date,
        time=time,
        location=location,
        game_type=game_type,
        entry_fee=entry_fee,
        max_players=max_players,
        details=details,
        organizers=organizers,
        players=players,
    )


def scrape_matches(comp_id: int) -> list[Match]:
    """Scrape all match results from the bracket page."""
    soup = fetch_page(f"{BASE_URL}/kisa/{comp_id}/kaavio/")

    bracket = soup.find("div", class_="list-bracket")
    if not bracket:
        return []

    matches: list[Match] = []
    current_round = "Unknown"
    current_race_to = 0

    # The matches div contains alternating h5 (round header) and
    # div.table-responsive (match table) as direct children.
    matches_div = bracket.find("div", class_="matches")
    if not matches_div:
        return []

    for child in matches_div.children:
        if not isinstance(child, Tag):
            continue

        if child.name == "h5":
            # Round header — extract name and race-to
            round_text = child.contents[0] if child.contents else ""
            current_round = str(round_text).strip()

            wins_span = child.find("span", class_=re.compile(r"round-wins"))
            if wins_span:
                wins_text = _text(wins_span)
                m = re.search(r"(\d+)", wins_text)
                if m:
                    current_race_to = int(m.group(1))
            continue

        # Process match rows from table-responsive divs
        for row in child.find_all("tr", class_="parent"):
            match_id = int(row.get("data-id", 0))
            status = row.get("data-match-status", "unknown")
            race_to = int(row.get("data-round-wins", current_race_to) or current_race_to)

            # Match number
            num_td = row.find("td", class_="match-number")
            match_num = 0
            if num_td:
                m = re.search(r"#(\d+)", _text(num_td))
                if m:
                    match_num = int(m.group(1))

            # Home player
            home_div = row.find("div", class_="home-name")
            home_name_el = home_div.find("span", class_="player-name") if home_div else None
            home_player = _text(home_name_el)

            home_score_el = row.find("span", class_=re.compile(r"\bhome\b.*\bscore\b"))
            home_score = int(_text(home_score_el)) if home_score_el and _text(home_score_el).isdigit() else 0

            # Away player
            away_div = row.find("div", class_="away-name")
            away_name_el = away_div.find("span", class_="player-name") if away_div else None
            away_player = _text(away_name_el)

            away_score_el = row.find("span", class_=re.compile(r"\baway\b.*\bscore\b"))
            away_score = int(_text(away_score_el)) if away_score_el and _text(away_score_el).isdigit() else 0

            # Winner
            winner = ""
            if home_score > away_score:
                winner = home_player
            elif away_score > home_score:
                winner = away_player

            # Table number
            table_td = row.find("td", class_="match-table")
            table_num = None
            if table_td:
                value_span = table_td.find("span", class_="value")
                if value_span:
                    m = re.search(r"(\d+)", _text(value_span))
                    if m:
                        table_num = int(m.group(1))

            # Duration
            duration = None
            if table_td:
                dur_span = table_td.find("span", class_="match-duration")
                if dur_span:
                    duration = _text(dur_span)

            matches.append(Match(
                match_id=match_id,
                match_number=match_num,
                round_name=current_round,
                race_to=race_to,
                home_player=home_player,
                home_score=home_score,
                away_player=away_player,
                away_score=away_score,
                winner=winner,
                table_number=table_num,
                duration=duration,
                status=status,
            ))

    return matches


def scrape_standings(comp_id: int) -> list[Standing]:
    """Scrape final standings from the results page."""
    soup = fetch_page(f"{BASE_URL}/kisa/{comp_id}/tulokset/")

    standings: list[Standing] = []

    # Standings are: <h5>1.</h5> followed by <div>Player Name</div> elements
    content = soup.find_all("div", class_="container content py-3")
    if len(content) < 2:
        return standings

    results_div = content[-1]  # Second container has the actual results
    col = results_div.find("div", class_="col-12")
    if not col:
        return standings

    current_rank = 0
    for child in col.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "h5":
            m = re.search(r"(\d+)", _text(child))
            if m:
                current_rank = int(m.group(1))
        elif child.name == "div" and current_rank > 0:
            player = _text(child)
            if player:
                standings.append(Standing(rank=current_rank, player=player))

    return standings


def scrape_competition(comp_id: int) -> CompetitionResult:
    """Scrape all data for a single competition."""
    info = scrape_info(comp_id)
    matches = scrape_matches(comp_id)
    standings = scrape_standings(comp_id)
    return CompetitionResult(info=info, matches=matches, standings=standings)


# ── Output formatters ────────────────────────────────────────────────────────


def to_json(result: CompetitionResult) -> str:
    return json.dumps(asdict(result), indent=2, ensure_ascii=False)


def to_csv(result: CompetitionResult, output_dir: Path) -> list[Path]:
    """Write matches and standings as separate CSV files. Returns file paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    comp_id = result.info.competition_id
    files = []

    # Matches CSV
    if result.matches:
        matches_path = output_dir / f"competition_{comp_id}_matches.csv"
        with open(matches_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(result.matches[0]).keys()))
            writer.writeheader()
            for m in result.matches:
                writer.writerow(asdict(m))
        files.append(matches_path)

    # Standings CSV
    if result.standings:
        standings_path = output_dir / f"competition_{comp_id}_standings.csv"
        with open(standings_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["rank", "player"])
            writer.writeheader()
            for s in result.standings:
                writer.writerow(asdict(s))
        files.append(standings_path)

    return files


def print_summary(result: CompetitionResult) -> None:
    """Print a human-readable summary to stdout."""
    info = result.info
    print(f"\n{'='*60}")
    print(f"  {info.name}")
    print(f"{'='*60}")
    if info.date:
        print(f"  Date:     {info.date}")
    if info.time:
        print(f"  Time:     {info.time}")
    if info.location:
        print(f"  Location: {info.location}")
    if info.game_type:
        print(f"  Game:     {info.game_type}")
    print(f"  Players:  {len(info.players)}")

    if result.matches:
        print(f"\n  Matches ({len(result.matches)}):")
        print(f"  {'-'*56}")
        for m in result.matches:
            marker = "<" if m.winner == m.home_player else " "
            marker2 = "<" if m.winner == m.away_player else " "
            print(f"  #{m.match_number:>2} [{m.round_name}]")
            print(f"       {m.home_player:>20} {m.home_score} - {m.away_score} {m.away_player}")

    if result.standings:
        print(f"\n  Final Standings:")
        print(f"  {'-'*56}")
        for s in result.standings:
            print(f"    {s.rank}. {s.player}")

    print()


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape TS-Pool competition results")
    parser.add_argument("competition_id", type=int, help="Competition ID (e.g. 1353)")
    parser.add_argument("--format", choices=["json", "csv", "summary"], default="summary",
                        help="Output format (default: summary)")
    parser.add_argument("--output", type=str, default="output",
                        help="Output directory for csv/json files (default: output/)")
    args = parser.parse_args()

    result = scrape_competition(args.competition_id)

    if args.format == "json":
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"competition_{args.competition_id}.json"
        path.write_text(to_json(result), encoding="utf-8")
        print(f"Written to {path}")
    elif args.format == "csv":
        files = to_csv(result, Path(args.output))
        for f in files:
            print(f"Written to {f}")
    else:
        print_summary(result)


if __name__ == "__main__":
    main()
