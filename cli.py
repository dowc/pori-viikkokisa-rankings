"""
Top-level CLI for the Pori Viikkokisa Rankings pipeline.

Usage:
    pori scrape 1353 1354              # Scrape competitions and regenerate site
    pori rebuild                       # Regenerate site from existing data
    pori deploy BUCKET                 # Upload to S3
    pori run 1353 1354 --bucket B      # Scrape + generate + deploy in one go
    pori season list                   # Show all seasons
    pori season new "Syksy 2026"       # Archive current season, start new one
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path


def cmd_scrape(args: argparse.Namespace) -> None:
    from generate_site import generate_site, load_db, save_db, calculate_rankings
    from tspool_scraper import scrape_competition
    from dataclasses import asdict

    db = load_db()

    for comp_id in args.competition_ids:
        if str(comp_id) in db["competitions"]:
            print(f"Competition {comp_id} already in database, skipping")
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
    print(f"Done — {len(rankings)} players across {len(db['competitions'])} competitions")


def cmd_rebuild(args: argparse.Namespace) -> None:
    from generate_site import generate_site, load_db, calculate_rankings

    db = load_db()
    print("Regenerating site from existing data...")
    generate_site(db)

    rankings = calculate_rankings(db)
    print(f"Done — {len(rankings)} players across {len(db['competitions'])} competitions")


def cmd_deploy(args: argparse.Namespace) -> None:
    from deploy_s3 import s3_sync

    print(f"Deploying to s3://{args.bucket}/\n")

    print("Uploading site...")
    s3_sync("site", args.bucket, "", delete=args.delete, dry_run=args.dry_run, cache_control="max-age=300")

    print("\nUploading data...")
    s3_sync("data", args.bucket, "data", delete=args.delete, dry_run=args.dry_run, cache_control="max-age=60")

    if not args.dry_run:
        print(f"\nDone! Site available at: http://{args.bucket}.s3-website-eu-west-1.amazonaws.com/")


def cmd_run(args: argparse.Namespace) -> None:
    """Full pipeline: scrape → generate → deploy."""
    # Scrape
    scrape_ns = argparse.Namespace(competition_ids=args.competition_ids)
    cmd_scrape(scrape_ns)

    # Deploy
    if args.bucket:
        print()
        deploy_ns = argparse.Namespace(bucket=args.bucket, delete=args.delete, dry_run=args.dry_run)
        cmd_deploy(deploy_ns)
    else:
        print("\nSkipping deploy (no --bucket specified)")


def cmd_season_new(args: argparse.Namespace) -> None:
    """Archive current season and start a new one."""
    from generate_site import (
        load_config, save_config, load_db, save_db, generate_site, slugify,
    )

    config = load_config()
    old_name = config["current_season"]
    old_slug = slugify(old_name)
    new_name = args.name

    start = date.fromisoformat(args.start) if args.start else date.today()
    end = start + timedelta(weeks=16)

    # Check for slug collision
    existing_slugs = {s["slug"] for s in config.get("seasons", [])}
    if old_slug in existing_slugs:
        print(f"Error: season '{old_name}' ({old_slug}) is already archived", file=sys.stderr)
        sys.exit(1)

    # Archive current data
    archive_dir = Path("data/seasons") / old_slug
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2("data/competitions.json", archive_dir / "competitions.json")
    print(f"Archived '{old_name}' -> data/seasons/{old_slug}/")

    # Update config
    config["seasons"].append({"name": old_name, "slug": old_slug})
    config["current_season"] = new_name
    config["season_start"] = start.isoformat()
    config["season_end"] = end.isoformat()
    save_config(config)

    # Reset current season
    save_db({"competitions": {}, "last_updated": None})

    # Regenerate all sites
    print("Regenerating sites...")
    generate_site(load_db())

    print(f"New season '{new_name}' started ({start} – {end})")


def cmd_discover(args: argparse.Namespace) -> None:
    """Find new Viikkokisat Pori competitions not yet in the database."""
    from tspool_scraper import scrape_listing
    from generate_site import load_db, generate_site, save_db, calculate_rankings
    from dataclasses import asdict
    from tspool_scraper import scrape_competition

    db = load_db()
    known_ids = set(db["competitions"].keys())
    max_known_id = max((int(i) for i in known_ids), default=0)

    print(f"Searching tspool.fi for '{args.filter}' (after ID {max_known_id})...")
    found = scrape_listing(name_filter=args.filter, stop_at_id=max_known_id)

    new = [(cid, name) for cid, name in found if str(cid) not in known_ids]

    if not new:
        print("No new competitions found.")
        return

    print(f"Found {len(new)} new competition(s):")
    for cid, name in new:
        print(f"  {cid}: {name}")

    if args.scrape:
        for cid, name in new:
            print(f"Scraping {cid}: {name}...")
            result = scrape_competition(cid)
            if not result.standings:
                print(f"  Skipping — no standings (competition not played)")
                continue
            db["competitions"][str(cid)] = {
                "info": asdict(result.info),
                "matches": [asdict(m) for m in result.matches],
                "standings": [asdict(s) for s in result.standings],
            }
        save_db(db)
        print("Generating site...")
        generate_site(db)
        rankings = calculate_rankings(db)
        print(f"Done — {len(rankings)} players across {len(db['competitions'])} competitions")

        if args.bucket:
            print()
            deploy_ns = argparse.Namespace(bucket=args.bucket, delete=False, dry_run=False)
            cmd_deploy(deploy_ns)
    else:
        ids = " ".join(str(cid) for cid, _ in new)
        print(f"\nRun with --scrape to add them, or manually: pori scrape {ids}")


def cmd_season_list(args: argparse.Namespace) -> None:
    """List all seasons."""
    from generate_site import load_config

    config = load_config()
    end = config.get("season_end") or "?"
    print(f"Current: {config['current_season']} (päättyy {end})")
    for s in config.get("seasons", []):
        print(f"  Archived: {s['name']} ({s['slug']}/")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pori",
        description="Pori Viikkokisa Rankings — scrape, generate, deploy",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scrape
    p_scrape = sub.add_parser("scrape", help="Scrape competitions and regenerate site")
    p_scrape.add_argument("competition_ids", nargs="+", type=int, help="Competition ID(s)")
    p_scrape.set_defaults(func=cmd_scrape)

    # rebuild
    p_rebuild = sub.add_parser("rebuild", help="Regenerate site from existing data")
    p_rebuild.set_defaults(func=cmd_rebuild)

    # discover
    p_discover = sub.add_parser("discover", help="Find new Viikkokisat Pori competitions on tspool.fi")
    p_discover.add_argument("--filter", default="Viikkokisat Pori", help="Name filter (default: 'Viikkokisat Pori')")
    p_discover.add_argument("--scrape", action="store_true", help="Automatically scrape and add found competitions")
    p_discover.add_argument("--bucket", help="S3 bucket to deploy to after scraping")
    p_discover.set_defaults(func=cmd_discover)

    # deploy
    p_deploy = sub.add_parser("deploy", help="Upload site and data to S3")
    p_deploy.add_argument("bucket", help="S3 bucket name")
    p_deploy.add_argument("--delete", action="store_true", help="Remove stale files from S3")
    p_deploy.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    p_deploy.set_defaults(func=cmd_deploy)

    # run (full pipeline)
    p_run = sub.add_parser("run", help="Scrape + generate + deploy in one go")
    p_run.add_argument("competition_ids", nargs="+", type=int, help="Competition ID(s)")
    p_run.add_argument("--bucket", help="S3 bucket (skip deploy if omitted)")
    p_run.add_argument("--delete", action="store_true", help="Remove stale files from S3")
    p_run.add_argument("--dry-run", action="store_true", help="Preview deploy without uploading")
    p_run.set_defaults(func=cmd_run)

    # season
    p_season = sub.add_parser("season", help="Manage seasons")
    season_sub = p_season.add_subparsers(dest="season_command", required=True)

    p_season_new = season_sub.add_parser("new", help="Archive current season and start a new one")
    p_season_new.add_argument("name", help="New season name (e.g. 'Syksy 2026')")
    p_season_new.add_argument("--start", help="Season start date YYYY-MM-DD (default: today)", default=None)
    p_season_new.set_defaults(func=cmd_season_new)

    p_season_list = season_sub.add_parser("list", help="List all seasons")
    p_season_list.set_defaults(func=cmd_season_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
