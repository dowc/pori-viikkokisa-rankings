# Pori Viikkokisa Rankings

Scrapes pool billiard competition results from [tspool.fi](https://tspool.fi) and generates a static HTML rankings site.

## Setup

```bash
uv sync
```

Commands are run via `uv run pori` (no need to activate the venv).

## Usage

### Scrape and generate site

```bash
uv run pori scrape 1353 1354    # scrape competitions and regenerate site
uv run pori rebuild              # regenerate site from existing data (no scraping)
```

### Deploy to S3

```bash
uv run pori deploy MY-BUCKET
uv run pori deploy MY-BUCKET --delete    # also remove stale files
uv run pori deploy MY-BUCKET --dry-run   # preview without uploading
```

### Full pipeline

```bash
uv run pori run 1353 1354 --bucket MY-BUCKET   # scrape + generate + deploy in one go
```

### Season management

```bash
uv run pori season list
uv run pori season new "Syksy 2026"    # archive current season, start new one
```

### View the site locally

```bash
python3 -m http.server 8080 --directory site
# Open http://localhost:8080
```

## How it works

- **Incremental** — Competition results are stored in `data/competitions.json`. Only new competitions are scraped; existing ones are skipped.
- **Points system** — 1st=8, 2nd=6, 3rd=4, 4th=3, 5th=2, 6th+=1. Shared placements receive equal points.
- **Static HTML** — Generated pages use Tailwind CSS (CDN) and are output to `site/`.

## Project structure

```
cli.py               # Main entry point (pori command)
tspool_scraper.py    # Scrapes a single competition from tspool.fi
generate_site.py     # Builds rankings and generates static HTML
deploy_s3.py         # Uploads site and data to S3
data/                # Local JSON database (gitignored)
site/                # Generated HTML pages (gitignored)
```
