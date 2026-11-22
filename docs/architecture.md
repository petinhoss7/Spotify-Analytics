# Spotify Analytics — Architecture

## DAG overview

```mermaid
flowchart LR
    subgraph EXT["Python extract scripts"]
        P1["scripts/load_raw.py<br>+ scripts/spotify_api"]
        P2["scripts/lastfm_api"]
        P3["scripts/musicbrainz_api"]
        P4["scripts/classifier<br>offline tag classification"]
    end

    subgraph RAW["RAW schema — DuckDB"]
        R1[("RAW_SPOTIFY_STREAMING<br>1 row = 1 play, JSON")]
        R2[("RAW_SPOTIFY_AUDIO_FEATURES")]
        R3[("RAW_SPOTIFY_ARTISTS")]
        R4[("RAW_SPOTIFY_TRACK_ARTISTS")]
        R5[("RAW_LASTFM_ARTIST_GENRES")]
        R6[("RAW_MUSICBRAINZ_ARTISTS")]
    end

    P1 --> R1 & R2 & R3 & R4
    P2 --> R5
    P3 --> R6
    P4 --> TGM

    subgraph STG["Staging — typed & renamed views"]
        S1["stg_spotify_history<br>flatten JSON · UTC · hashed IP"]
        S2["stg_audio_features<br>flatten + dedup by track"]
        S3["stg_spotify_artists"]
        S4["stg_spotify_artists_tags<br>1 row per artist × tag"]
        S5["stg_spotify_track_artists"]
        S6["stg_lastfm_artists_tags"]
        S7["stg_musicbrainz_artists_tags"]
    end

    R1 --> S1
    R2 --> S2
    R3 --> S3
    R4 --> S5
    R5 --> S6
    R6 --> S7
    S3 --> S4

    subgraph SEED["Seeds — closed list + offline classification"]
        DGS[["discogs_genre_styles<br>closed Discogs list (JSON)"]]
        TGM[["tag_genre_map<br>raw tag -> genre + style"]]
    end

    subgraph INT["Intermediate — business logic, tables"]
        I1["int_spotify_streams_deduped<br>1 row per stream"]
        I2["int_spotify_streams_enriched<br>music-only + listening features"]
        I3["int_tracks_base<br>1 row per track: nb_streams, first/last play"]
        I4["int_tracks<br>tracks + audio features"]
        I5["int_artists_tags<br>tags classified to Discogs genres/styles"]
        I6["int_artists<br>artist profile + final genres/styles attribution"]
        I7["int_tracks_artists<br>track × artist bridge + collab flag"]
        I8["int_source_tag_classification<br>line-by-line: artist × source × raw tag"]
        I9["int_source_tag_cross_comparison<br>genre & style Jaccard per artist"]
        I10["int_source_tag_comparison_summary<br>per-source coverage & method mix"]
        I11["int_source_genre_pair_comparison<br>genre confusion matrix per source pair"]
        I12["int_source_style_pair_comparison<br>style confusion matrix per source pair"]
        I13["int_artists_genre_attribution<br>final 1-2 genres + 1-2 styles + confidence"]
        I14["int_artists_tag_scores<br>row-level evidence weights"]
        I15["int_artists_genre_scores<br>score + share per artist × genre"]
    end

    subgraph MARTS["Marts — serving layer, tables"]
        F1["fct_streams<br>1 row = 1 music stream + lead artist"]
        F2["fct_genre_listening<br>minutes per month × genre<br>(evidence-proportional)"]
    end

    S1 --> I1 --> I2
    S1 --> I3
    I3 --> I4
    S2 --> I4
    S4 --> I5
    S6 --> I5
    S7 --> I5
    TGM --> I5
    DGS -.-> I5
    S4 --> I8
    S6 --> I8
    S7 --> I8
    TGM --> I8
    I8 --> I9
    I8 --> I10
    I8 --> I11
    I8 --> I12
    I8 --> I14
    I14 --> I15
    I14 --> I13
    I15 --> I13
    I13 --> I6
    DGS -.-> I13
    S3 --> I6
    S6 -.-> I6
    S7 -.-> I6
    S5 --> I7
    I6 --> I7
    I2 --> F1
    I7 --> F1
    I6 --> F1
    F1 --> F2
    I7 --> F2
    I15 --> F2
```

Solid arrows = model dependencies, dashed = secondary metadata joins.
Interactive version: `dbt docs generate` then `dbt docs serve`.

## Role of each model

### Sources (`raw` schema, loaded by Python scripts)

| Source | Loaded by | Content |
|---|---|---|
| `RAW_SPOTIFY_STREAMING` | `load_raw.py` (Spotify extended history export) | One JSON record per play: track, timestamp, ms played, platform, reasons, IP… |
| `RAW_SPOTIFY_ARTISTS` | `load_raw.py` + `scripts/spotify_api` | Artist metadata via RapidAPI: followers, popularity, genres |
| `RAW_SPOTIFY_TRACK_ARTISTS` | `load_raw.py` + `scripts/spotify_api` | Track ↔ artist associations |
| `RAW_SPOTIFY_AUDIO_FEATURES` | `load_raw.py` + `scripts/spotify_api` | Audio features per track (JSON): danceability, energy, valence… |
| `RAW_LASTFM_ARTIST_GENRES` | `scripts/lastfm_api` | Last.fm top tags per artist |
| `RAW_MUSICBRAINZ_ARTISTS` | `scripts/musicbrainz_api` | MusicBrainz artist metadata: country, dates, tags |

### Staging (views, 1:1 with source — only typing, renaming, flattening)

| Model | Role |
|---|---|
| `stg_spotify_history` | Flattens JSON plays, types columns, normalizes timestamps to UTC, hashes IP (PII) |
| `stg_audio_features` | Flattens audio-features JSON, dedupes to one row per track |
| `stg_spotify_artists` | Typed artist metadata |
| `stg_spotify_artists_tags` | Unnests genre lists → one row per artist × tag |
| `stg_spotify_track_artists` | Typed track ↔ artist pairs |
| `stg_lastfm_artists` / `stg_lastfm_artists_tags` | Parses Last.fm JSON, extracts tags (deduped) |
| `stg_musicbrainz_artists` / `stg_musicbrainz_artists_tags` | Typed MusicBrainz metadata + flattened tags |

### Seeds (closed list + offline classification)

| Seed | Role |
|---|---|
| `discogs_genres_styles` | Closed Discogs list flattened from `discogs_genres_styles.json` (15 genres x 372 styles); referential-integrity reference for tests |
| `tag_genre_map` | 1 row per unique raw tag (12,697): `is_genre_tag`, `discogs_genre`, `discogs_style`, `match_method`, `match_score`, `confidence`. Produced offline by `scripts/classifier/classify_tags.py` |
| `tag_overrides` | Human-curated overrides (62 tags): fixes the answer and the tag-specificity `confidence` before any automatic layer runs. Not materialized in the warehouse |
| `tag_aliases` | Alias rewrites consumed by the classifier script only |
| `tag_gold` | Reviewed 209-tag sample used as the arbiter by `eval_classify.py`. Not materialized in the warehouse |

#### Tag classification (offline, `scripts/classifier/`)

Layers, in priority order per tag: curated overrides
(`seeds/tag_overrides.csv`) -> normalization -> exact match against the
closed list -> alias rewrite (`seeds/tag_aliases.csv`) -> token-boundary
containment of a closed-list key (longest key wins, ties abstain) -> LLM
classification (GLM via OpenRouter, closed list in the system prompt,
server-side validation) -> review file for anything left. Pure-noise tags
(numbers, hex, decades) and workflow artifacts (a Lidarr batch leaked
`funk_add_to_lidarr_batch_<n>` 32 times) are flagged non-genre
deterministically. LLM answers
are cached in `data/tag_llm_cache.json`, so re-runs are free and resumable.
Ambiguous style names shared by several genres ("dub", "disco", "ska"...)
never match deterministically; they are always decided by the LLM layer.

Token containment is the only heuristic layer left, and the one that held
the most unvalidated weight. `scripts/classifier/context_audit.py` compares
each tag with the dominant genre of the artists' *other* tags; it found the
layer at 64.8% agreement with a recognisable failure mode (the modifier is
matched instead of the genre head: `jazz beats` -> Jazz though its 100
artists are Hip Hop 79%). The audit is now a standing tool, and the
corrected tags are curated overrides.

Two independent reliability factors score every tag row:

- `match_method` -> **method weight** (reliability of the mechanism):
  manual/exact/alias 1.0, fuzzy 0.9, llm 0.8.
- `confidence` -> **tag specificity** (reliability of the meaning), stored in
  the seed: 1.0 for every automatic layer, lowered only by the curated
  overrides for tags that do not determine a genre by themselves
  ("dance", "indie", "oldies", "instrumental"...).

`scripts/classifier/quality_report.py` prints the metrics used to judge a
change: attribution coverage, primary-genre distribution, MusicBrainz
structured-genre confirmation (an external referee never fed to the
classifier), cross-source Jaccard and the share of hedged evidence.

### Intermediate (tables, business logic)

| Model | Role |
|---|---|
| `int_spotify_streams_deduped` | One row per stream — removes plays duplicated across export files (keeps latest load) |
| `int_spotify_streams_enriched` | Music-only streams + listening features: `stream_date`, hour, weekday, `is_meaningful_listen` (≥30 s) |
| `int_tracks_base` | One row per track: stream count, first/last played, latest metadata |
| `int_tracks` | Track dimension: base + audio features |
| `int_artists_tags` | Standalone fact table: 1 row per artist × tag classified to a Discogs genre/style (non-genre tags excluded) — the queryable detail behind the attribution |
| `int_source_tag_classification` | Line-by-line comparison base: faithful union of the 3 staging tag views (1 row = artist × source × raw tag, nothing filtered) left-joined to `tag_genre_map`, with `classification_status` = genre / non_genre / empty_tag / unmapped |
| `int_source_tag_cross_comparison` | Cross-source agreement at artist level: pivoted Discogs genre and style sets per source, shared/union sets, Jaccard `agreement_score` (genre) and `subgenre_agreement_score` (style); artists genre-classified in ≥2 sources |
| `int_source_tag_comparison_summary` | Per-source figures: rows, distinct tags/artists, genre & style rates, method mix (exact/alias/fuzzy/llm/noise), populations excluded from scoring |
| `int_source_genre_pair_comparison` | Confusion matrix per source pair at genre level: (genre_a, genre_b) co-occurrence counts + mean pairwise Jaccard |
| `int_source_style_pair_comparison` | Confusion matrix per source pair at style level (style-name-only matching), same structure |
| `int_artists_genre_attribution` | Final attribution: 1 row per artist — primary + secondary genre (rule-gated) and styles, weighted-score based, with `primary_share`, `combined_confidence`, `is_ambiguous` |
| `int_artists` | Consolidated artist profile: Spotify + Last.fm + MusicBrainz data + the final Discogs attribution embedded from `int_artists_genre_attribution` (primary/secondary genre & style, confidence, ambiguity flag) |
| `int_tracks_artists` | Track × artist bridge with artist count and `is_collaboration` flag |
| `int_artists_tag_scores` | Row-level evidence weights: 1 row = artist × source × genre-classified tag, `row_weight = method_weight × confidence × ln(1 + tag_count)` — the single definition consumed by attribution and marts |
| `int_artists_genre_scores` | Genre evidence scores: 1 row = artist × genre (ALL scored genres), `genre_score` with cross-source bonus + `genre_share` (0-1, shares sum to 1 per artist) |

#### Source tag comparison & final attribution

`int_source_tag_classification` is the audit base: every staging tag line
keeps its raw value and its classification outcome, so any source can be
drilled line by line (guards: row-count reconciliation against the staging
views and zero `unmapped` lines). On top of it:

- **Cross-source comparison**: for each artist, the genre (and style) sets
  derived independently from each source are compared with a simple Jaccard
  score (shared / union). Pairwise confusion matrices expose systematic
  disagreements between sources (e.g. Rock vs Pop for the same artists).
- **Final attribution** (`int_artists_genre_attribution`): genres are scored
  with an explainable weighted sum — `row_weight = method_weight ×
  confidence × ln(1 + tag_count)` (method_weight: manual/exact/alias 1.0,
  fuzzy 0.9, llm 0.8; confidence: tag specificity from the seed, 1.0 unless a
  curated override lowered it), genre score
  multiplied by `(1 + 0.5 × (distinct_sources − 1))` so cross-source
  agreement outranks tag volume. Primary = top score; secondary kept only
  with ≥2 sources and ≥50% of the primary score (tunable vars
  `attribution_min_secondary_*`); the raw runner-up, ratio and source count
  are stored even when rejected. Styles are ranked only among rows whose
  genre is a final genre, so a sous-genre is always coherent with its
  final genre. `combined_confidence = 0.6 × primary_share +
  0.4 × (sources / 3)`; `is_ambiguous` flags near-ties (runner-up ratio
  ≥ 0.75).

#### Score models (shared by attribution and marts)

`int_artists_tag_scores` / `int_artists_genre_scores` define the
scoring math once (row weights, genre scores, `genre_share`). The
attribution model and the listening marts both consume them, so
sanctioned attribution and evidence-proportional listening attribution
can never drift apart (guards:
`test_attribution_scores_match_genre_scores`,
`test_genre_scores_shares_sum`).

### Marts (serving layer)

| Model | Role |
|---|---|
| `fct_streams` | Event fact: 1 row = 1 music stream, reconciled to `int_spotify_streams_enriched` (rows + minutes); denormalized lead artist (name-matched, deterministic fallback), `artist_count`, `is_collaboration`, `lead_primary_genre` |
| `fct_genre_listening` | Listening minutes per month × genre. Evidence-proportional attribution: stream minutes split across track artists (`minutes / artist_count`), then across ALL the artist's scored genres by `genre_share`. Two explicit buckets (`unclassified` = artist without genre evidence, `no_artist_data` = track absent from the bridge) keep every month's total equal to `fct_streams`; per-artist genre ranking follows the tag evidence (no gate-induced rank flips) |

Per-artist distributions on real data: Childish Gambino → Hip Hop
73.0 / Funk / Soul 19.9 / Rock 7.1; Lana Del Rey → Pop 49.0 / Rock
36.9 / Electronic 9.5 / FW&C 4.6.
