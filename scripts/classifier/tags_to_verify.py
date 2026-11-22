#!/usr/bin/env python3
"""Build the hand-verification list of the most-used tags.

Writes a CSV pre-filled with the *current* classification (from
seeds/tag_genre_map.csv) and empty verdict columns, so reviewing means
filling in only the rows that are wrong.

Usage is computed directly from the three staging tag views, so it does not
depend on the classification at all and the list is stable across changes.

`variant_family` groups spellings of the same word: lowercase, accents
dropped, every non-alphanumeric character removed, explicit suffixes
(music / musique / sounds) stripped. Plural is deliberately KEPT, so
"afrobeat" and "afrobeats" stay in separate families - they are different
genres - while "chillout", "chill out" and "chill-out" share one.

Usage::

    python scripts/classifier/tags_to_verify.py                 # top 200 by usage
    python scripts/classifier/tags_to_verify.py --top 500
    python scripts/classifier/tags_to_verify.py --genre-only
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
SEED_CSV = ROOT / "seeds" / "tag_genre_map.csv"
OUT_CSV = ROOT / "seeds" / "tags_to_verify.csv"
DB_PATH = ROOT / "data" / "spotify.duckdb"

SUFFIXES = ("music", "musique", "musik", "musica", "sounds", "sound")

HEADER = [
    "raw_tag",
    "variant_family",
    "sources",
    "artists",
    "tag_rows",
    "current_is_genre_tag",
    "current_genre",
    "current_style",
    "current_match_method",
    "verdict",
    "correct_genre",
    "correct_style",
    "comment",
]

STAGING = """
with tags as (
    select lower(trim(tag_name)) as raw_tag, artist_id, 'lastfm' as source
    from stg_lastfm_artists_tags
    union all
    select lower(trim(tag_name)), artist_id, 'musicbrainz'
    from stg_musicbrainz_artists_tags
    union all
    select lower(trim(tag_name)), artist_id, 'rapidapi'
    from stg_spotify_artists_tags
)
select raw_tag,
       count(*) as tag_rows,
       count(distinct artist_id) as artists,
       string_agg(distinct source, ',' order by source) as sources
from tags
where raw_tag <> ''
group by raw_tag
"""


def variant_family(tag: str) -> str:
    s = unicodedata.normalize("NFKD", tag)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    for suffix in SUFFIXES:
        if len(s) > len(suffix) + 2 and s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def load_seed(path: Path = SEED_CSV) -> dict[str, dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return {row["raw_tag"]: row for row in csv.DictReader(f)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=200, help="how many tags, by usage")
    parser.add_argument("--genre-only", action="store_true",
                        help="only tags currently classified as genres")
    parser.add_argument("--min-artists", type=int, default=1)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--seed", type=Path, default=SEED_CSV)
    parser.add_argument("--out", type=Path, default=OUT_CSV)
    args = parser.parse_args(argv)

    seed = load_seed(args.seed)
    con = duckdb.connect(str(args.db), read_only=True)
    try:
        usage = con.execute(STAGING).fetchall()
    finally:
        con.close()

    rows = []
    for raw_tag, tag_rows, artists, sources in usage:
        seed_row = seed.get(raw_tag)
        is_genre = (seed_row or {}).get("is_genre_tag") == "true"
        if args.genre_only and not is_genre:
            continue
        if artists < args.min_artists:
            continue
        rows.append((tag_rows, {
            "raw_tag": raw_tag,
            "variant_family": variant_family(raw_tag),
            "sources": sources,
            "artists": artists,
            "tag_rows": tag_rows,
            "current_is_genre_tag": "true" if is_genre else "false",
            "current_genre": (seed_row or {}).get("discogs_genre", ""),
            "current_style": (seed_row or {}).get("discogs_style", ""),
            "current_match_method": (seed_row or {}).get("match_method", ""),
            "verdict": "",
            "correct_genre": "",
            "correct_style": "",
            "comment": "",
        }))

    rows.sort(key=lambda r: (-r[0], r[1]["raw_tag"]))
    selected = [r[1] for r in rows[: args.top]]

    # report the coverage of the selection, on every tag row in the warehouse
    total_rows = sum(r[0] for r in rows)
    covered = sum(r["tag_rows"] for r in selected)

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(selected)

    print(f"wrote {args.out}")
    print(f"  {len(selected)} tags, sorted by usage")
    print(f"  they cover {covered}/{total_rows} tag rows = {covered / total_rows:.1%} "
          f"of all artist x tag evidence")
    print(f"  tags with a classification: "
          f"{sum(1 for r in selected if r['current_match_method'])}")
    print("  fill `verdict` (ok / wrong) and, when wrong, correct_genre / "
          "correct_style / comment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
