# Spotify Analytics

[![dbt CI](https://github.com/petinhoss7/Spotify-Analytics/actions/workflows/dbt_ci.yml/badge.svg)](https://github.com/petinhoss7/Spotify-Analytics/actions/workflows/dbt_ci.yml)

A dbt + DuckDB analytics project that turns a Spotify streaming history into
trustworthy listening analytics — the flagship question being **how much time
do I actually spend listening to each genre?**

Genre attribution is not a single label copied from an API. Three independent
tag sources (Spotify genres, Last.fm, MusicBrainz) are reconciled against the
closed Discogs taxonomy, scored with explainable weights, and listening minutes
are then split across an artist's genres **proportionally to the evidence**.

```
Childish Gambino  ->  Hip Hop 73.0% | Funk / Soul 19.9% | Rock 7.1%
Lana Del Rey      ->  Pop 49.0% | Rock 36.9% | Electronic 9.5% | FW&C 4.6%
```

## How it works

```mermaid
flowchart LR
    A[Python extracts<br/>Spotify / Last.fm / MusicBrainz] --> R[(RAW<br/>DuckDB)]
    R --> S[Staging<br/>typed views]
    S --> I[Intermediate<br/>business logic, tables]
    I --> M[Marts<br/>fct_streams, fct_genre_listening]
    C[Offline tag classifier<br/>rules + LLM] --> T[[tag_genre_map seed]]
    T --> I
```

| Layer | What it does |
|---|---|
| `scripts/` | Loads the Spotify export, enriches artists/tracks via APIs, classifies raw tags offline |
| `models/staging/` | Flattens JSON, types columns, normalizes timestamps to UTC, hashes IPs (PII) |
| `models/intermediate/` | Deduplication, listening features, artist profiles, cross-source comparison, genre scoring & attribution |
| `models/marts/` | `fct_streams` (one row per music stream) and `fct_genre_listening` (minutes per month x genre) |
| `seeds/` | Closed Discogs taxonomy (15 genres / 372 styles), the 12,697-tag classification map, and the curated tag overrides |
| `tests/` | Singular reconciliation and business-rule tests |

Full DAG and model-by-model documentation: [`docs/architecture.md`](docs/architecture.md).
Interactive version: `dbt docs generate && dbt docs serve`.

### Genre attribution in one paragraph

Every genre-classified tag becomes a weighted row:
`row_weight = method_weight x confidence x ln(1 + tag_count)`, where
`method_weight` is the reliability of the mechanism (manual/exact/alias 1.0,
fuzzy 0.9, LLM 0.8) and `confidence` is the tag's specificity (1.0 by default,
lowered by the curated `seeds/tag_overrides.csv` for generic tags such as
`dance`, `indie` or `oldies`, which do not determine a genre by themselves).
Row weights are summed per artist x genre and multiplied by a cross-source
bonus `1 + 0.5 x (distinct_sources - 1)` so agreement outranks tag volume. The
top genre is the primary; a second genre is kept only with two sources and at
least 50% of the primary score. `genre_share` (shares sum to 1 per artist) is
what `fct_genre_listening` uses to split listening time across **all** scored
genres. Styles are ranked only within the final genres, so a sub-genre is
always coherent with its parent genre.

## Data sources

| Raw table | Produced by | Content |
|---|---|---|
| `RAW_SPOTIFY_STREAMING` | `scripts/load_raw.py` | One JSON record per play (export files, Parquet) |
| `RAW_SPOTIFY_ARTISTS` | `scripts/spotify_api` (RapidAPI) | Artist metadata + Spotify genres |
| `RAW_SPOTIFY_TRACK_ARTISTS` | `scripts/spotify_api` | Track ↔ artist associations |
| `RAW_SPOTIFY_AUDIO_FEATURES` | `scripts/spotify_api` | Danceability, energy, valence, tempo… |
| `RAW_LASTFM_ARTIST_GENRES` | `scripts/lastfm_api` | Top Last.fm tags per artist |
| `RAW_MUSICBRAINZ_ARTISTS` | `scripts/musicbrainz_api` | Country, dates, community tags |

Credentials live in `.env` (copy `.env.example`). The `raw` schema and the
DuckDB file (`data/spotify.duckdb`) are local only and never committed.

## Quick start

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
dbt deps
```

With production data already loaded into `data/spotify.duckdb`:

```bash
dbt build                          # seeds + models + 169 tests
dbt docs generate && dbt docs serve
```

### Run the pipeline on the CI fixture

You do not need the real export to validate the whole DAG — `ci/seed_fixture.py`
creates a small but complete DuckDB database (5 artists, 8 tracks, streams over
two months, every reconciliation bucket):

```bash
python ci/seed_fixture.py
dbt build --profiles-dir ci --target ci
```

### Refresh the data

```bash
python scripts/load_raw.py                       # Spotify export (Parquet)
python scripts/spotify_api/extract_artist_genres.py
python scripts/lastfm_api/extract_lastfm_artist_genres.py
python scripts/musicbrainz_api/extract_musicbrainz_artist_details.py
python scripts/classifier/classify_tags.py       # rewrites seeds/tag_genre_map.csv
dbt build
```

The classifier layers (normalization → exact → alias → token containment → LLM
→ review) are cached in `data/tag_llm_cache.json`, so re-runs are free and
resumable.

## Data quality

`dbt build` runs 171 tests, including 14 singular tests that guard the logic
rather than the columns:

- `fct_streams` and `fct_genre_listening` reconcile against their upstream
  models (rows and minutes), and genre shares sum to 1 per month;
- every staging tag is mapped (no silently dropped tags) and every
  `(genre, style)` pair belongs to the closed Discogs list;
- attribution reconciles with the line-by-line classification, its scores match
  `int_artists_genre_scores`, the secondary-genre rule holds, and each style is
  coherent with its parent genre.

Failures are stored in the `test_failures` schema (`+store_failures: true`).

The classifier has its own unit tests (57, run in CI) and an observational
quality report:

```bash
python -m unittest discover -s scripts/classifier -p "test_*.py"
python scripts/classifier/quality_report.py
```

The report tracks the metrics used to judge a classification change, including
the **MusicBrainz structured-genre confirmation rate** — MusicBrainz's
`genres` field is never fed to the classifier, so it acts as an external
referee for the tag-based attributions.

### Curated tag overrides

`seeds/tag_overrides.csv` fixes 30 high-volume tags by hand, before any
automatic layer. It carries two kinds of decisions:

- tags that are **not genres** and must not be forced into one:
  `indie` (Rock 0.30 vs Pop 0.28 — a coin flip across 1,751 artists),
  `oldies`, `urban`, `instrumental` (Discogs lists that style only under
  Hip Hop, which mislabelled 1,177 artists);
- tags that do not determine a genre **by themselves**, kept as weak priors so
  an artist's specific tags always outrank them: `dance`, `lo-fi`, `chillout`,
  `electronica`, `edm`, `club`, `progressive`, `singer-songwriter`...

Each row stores the measured justification (the dominant-genre share among the
artists carrying the tag). The overrides are deliberately conservative: they
change the primary genre of 507 artists (3.4%).

### Gold set: the arbiter

`seeds/tag_gold.csv` is a 150-tag sample (40 highest-usage, 30 carrying an
ambiguous taxonomy key, 80 random) pre-filled with the current classification,
so reviewing means editing only the rows you disagree with. The generator
flags rows whose data-derived signal disagrees with the label, so attention
goes where it matters:

```bash
python scripts/classifier/gold_sample.py    # (re)generate the sample
python scripts/classifier/eval_classify.py  # score the seed against it
```

`eval_classify.py` reports accuracy overall, per classification method and per
usage bucket, then fails below a threshold. It runs in CI, so no change to the
classifier can land unmeasured. It is also the honest answer to "is this
change an improvement?": without it, swapping a model or promoting a layer just
replaces one black box with another.

The 7 disagreements the first run surfaced already fixed two systematic bugs:
`rhythm and blues` was resolved to *Blues* by a containment match on the token
`blues` even though the phrase is an ambiguous taxonomy key (now abstains and
resolves through an explicit alias to `Funk / Soul | Rhythm & Blues`), and
`noise pop` was resolved to *Pop* via the generic token `pop` while its artists
are Rock.

## CI

`.github/workflows/dbt_ci.yml` runs on every push and pull request:

1. installs `dbt-duckdb`;
2. `dbt deps`;
3. generates the synthetic fixture (`ci/seed_fixture.py`);
4. runs `dbt build --target ci` (28 models/seeds + 169 tests).

No credentials or private data are needed — the fixture database is generated
in the job and git-ignored.

## Repository layout

```
.
├── ci/                     # CI profile + synthetic fixture generator
├── data/                   # local DuckDB database and LLM cache (git-ignored)
├── docs/architecture.md    # DAG, model roles, attribution rules
├── extracts/               # raw API exports (git-ignored)
├── models/
│   ├── staging/            # typed views, 1:1 with sources
│   ├── intermediate/       # business logic (tables)
│   └── marts/              # serving layer (tables)
├── seeds/                  # Discogs taxonomy, tag map, aliases
├── scripts/                # ingestion + offline tag classifier
├── tests/                  # singular reconciliation / business-rule tests
└── dbt_project.yml
```

## Current state

- History covered: **2018-09-23 → 2026-02-04**, 175,484 raw plays → 173,659
  music streams.
- 17,369 artists, 39,788 tracks, 14,699 artists with a genre attribution
  (2,670 unclassified), 507 of them decided by a curated generic tag.
- 12,697 raw tags classified: 30 curated overrides, 385 exact, 46 alias,
  1,860 containment, 10,272 LLM, 104 noise.
- Independent checks: **91.0%** of the comparable artists have their primary
  genre confirmed by MusicBrainz's structured `genres` field; mean cross-source
  Jaccard is **0.641** at genre level and 0.384 at style level.
- Last full build: **199/199 nodes green** (28 models/seeds, 171 tests).
