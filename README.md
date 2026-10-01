# PAX-RTP-Index

*Racers Theoretical Performance (RTP) / PAX*

----

This repository contains RTP/PAX data in a machine-readable format.  The values are used in SCCA Solo/Autocross events.

*The RTP/PAX data has been sourced from [Solotime - PAX/RTP Index](https://solotime.info/pax/) - hosted by [Solo Performance Specialties, LLC.](https://www.soloperformance.com/)*

## Files

| Path | Contents |
|---|---|
| `JSON/<year>.json`, `YAML/<year>.yaml` | One year's indices: `{"2026": {"AS": 0.83, ...}}` |
| `JSON/latest.json`, `YAML/latest.yaml` | The newest published year, same shape |
| `rtp.json`, `rtp.yaml` | Every year by class, with SCCA class name, category, whether that classification is verified, and class lineage ([schema](Schema/rtp.schema.json)) |
| `CSV/` | **Canonical data.** Everything above is generated from these files |
| `Schema/` | JSON Schemas for the generated files |

Stable URLs for software:

```
https://raw.githubusercontent.com/andrewdefilippis/PAX-RTP-Index/master/JSON/latest.json
https://raw.githubusercontent.com/andrewdefilippis/PAX-RTP-Index/master/JSON/<year>.json
https://raw.githubusercontent.com/andrewdefilippis/PAX-RTP-Index/master/rtp.json
```

### Canonical CSV files

| File | Columns | Notes |
|---|---|---|
| `CSV/rtp.csv` | `year,class,index,label` | `index` exactly as published (e.g. `0.820`); `label` is the verbatim page text (e.g. `AST(STR)`) |
| `CSV/classes.csv` | `class,first_year,last_year,name,category,status,source` | SCCA class name and category for a span of years with one citation; empty `last_year` = current. `status` is `verified` (cited from an SCCA source for those years) or `unverified` (carried from a neighboring year, or unknown) |
| `CSV/lineage.csv` | `year,class,predecessor,relation,source` | `year` is the first season of the new class. `renamed` = the predecessor's cars continue under the new code; `derived` = the new class took some or all of the predecessor's cars |
| `CSV/sources.csv` | `year,url,page_last_update,retrieved_at,sha256` | Where and when each year was fetched, and the page's own "Last update" date |

### Categories and verification

`Name` and `SoloCategory` use the names printed in that year's SCCA National Solo Rules (for example, the Street category was "Stock" until 2013). `ClassificationVerified` is `false` where no SCCA source for that year was available and the classification was carried from a neighboring year, or where SCCA no longer lists a class that solotime still publishes an index for. For a few early classes (T-1/T-2/T-3 in 1998, FJr, SFJr) no source names them, so `Name` and `SoloCategory` are `null`.

### Class codes are not continuous identities

SCCA reuses and restructures class codes. For example, in 2009 the former `STS` became `ST` and the former `STS2` became `STS`. In 2014 every Stock class became a one-year Street-R class (`AS` → `ASR`) while the code `AS` was reused for the new Street class. In 2025 Street Touring was reorganized and `STR` cars were split between `AST` and `CST`. A class code's history in `rtp.json` is the history of that *code*. Use `Predecessors`/`Successors` (or `CSV/lineage.csv`) to follow cars across changes.

## Updates

A [scheduled workflow](.github/workflows/update-rtp.yml) checks solotime.info every Monday for the newest published year and the year before it. When a page changes, including mid-season revisions, it opens a pull request with a summary of added, removed, and changed indices. A new class needs a row in `CSV/classes.csv` before it can be merged; such PRs open as drafts labeled `needs-classification`.

Maintainer notes:

* Bot PRs are opened with the workflow's `GITHUB_TOKEN`, which does not trigger CI. Validation results are included in the PR description, and pushing a commit to the PR branch runs CI.
* GitHub disables scheduled workflows in public repositories after 60 days without repository activity. If that happens, re-enable "Update RTP data" from the Actions tab.
* "Allow GitHub Actions to create and approve pull requests" must be enabled in the repository's Actions settings.
* The uv version used by the workflows is pinned together with its sha256 in `.github/workflows/*.yml`. Dependabot does not update these; bump both by hand from the [uv release](https://github.com/astral-sh/uv/releases) `uv-x86_64-unknown-linux-gnu.tar.gz.sha256` file.

## Running locally

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12+ if needed).

```sh
uv sync                                               # create .venv from uv.lock
uv run Scripts/rtp_web_scraper.py                     # newest year and the one before it
uv run Scripts/rtp_web_scraper.py --year 2024         # specific year(s); repeatable
uv run Scripts/rtp_web_scraper.py --all               # every year since 1995 (~6 minutes)
uv run Scripts/rtp_web_scraper.py --report report.md --html-dir /tmp/html  # change report, raw pages
uv run Scripts/rtp_files_generator.py                 # regenerate JSON/YAML from CSV/
uv run pytest
```

Dependencies are declared in `pyproject.toml` and locked with hashes in `uv.lock`. `uv lock --upgrade` refreshes the lock; `exclude-newer = "1 week"` keeps it from picking up releases less than a week old.

The scraper honors solotime.info's 10 second crawl delay. Edit `CSV/` by hand to correct data, then regenerate. Never edit the generated JSON/YAML directly.
