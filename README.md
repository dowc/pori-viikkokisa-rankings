# Pori Viikkokisa Rankings

Scrapes pool billiard competition results from [tspool.fi](https://tspool.fi) and generates a static HTML rankings site.

## Setup

```bash
pip install -r requirements.txt
# or
pip install requests beautifulsoup4
```

## Usage

### Scrape a single competition

```bash
python3 tspool_scraper.py 1353
python3 tspool_scraper.py 1353 --format json
python3 tspool_scraper.py 1353 --format csv
```

### Generate rankings site

```bash
# Add a new competition and generate site
python3 generate_site.py 1353

# Add multiple competitions
python3 generate_site.py 1340 1345 1353

# Regenerate site from existing data (no scraping)
python3 generate_site.py --rebuild
```

### View the site

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
tspool_scraper.py    # Scrapes a single competition from tspool.fi
generate_site.py     # Builds rankings and generates static HTML
data/                # Local JSON database (gitignored)
site/                # Generated HTML pages (gitignored)
```
