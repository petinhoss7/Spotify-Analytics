#!/usr/bin/env python3
"""Build the evaluation sample used to judge the tag classification.

The file is a *review* artifact: it is pre-filled with the current
classification, so reviewing means editing only the rows you disagree with.
It is never materialized in the warehouse (disabled seed).

Three strata, so a change cannot silently trade quality on one for another:

  top      the highest-usage tags (a tag's weight is its artist coverage;
           the head of the distribution carries most of the evidence)
  ambiguous tags carrying a taxonomy key that exists under several genres
           ("hardcore", "dub", "disco", "ska"...), the ones no
           deterministic layer may resolve
  random   a reproducible random draw from the rest, to catch regressions
           outside the head

Usage::

    python scripts/classifier/gold_sample.py
    python scripts/classifier/gold_sample.py --top 40 --ambiguous 30 --random 80

Reviewing:
  * keep a row as is when you agree with it
  * fix is_genre_tag / discogs_genre / discogs_style when you disagree
  * leave `note` free-form; the generator fills it with the data-derived
    signal so the rows worth a look are flagged in advance
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify_tags as ct  # noqa: E402

DB_PATH = ROOT / "data" / "spotify.duckdb"
SEED_CSV = ROOT / "seeds" / "tag_genre_map.csv"
GOLD_CSV = ROOT / "seeds" / "tag_gold.csv"

HEADER = [
    "raw_tag",
    "is_genre_tag",
    "discogs_genre",
    "discogs_style",
    "usage_artists",
    "current_match_method",
    "note",
]

WEAK_SHARE = 0.35


def load_seed() -> dict[str, dict]:
    with open(SEED_CSV, encoding="utf-8", newline="") as f:
        return {row["raw_tag"]: row for row in csv.DictReader(f)}


def load_usage() -> dict[str, int]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = con.execute(
            """
            select raw_tag, count(distinct artist_id)
            from int_artists_tag_scores
            group by 1
            """
        ).fetchall()
    finally:
        con.close()
    return dict(rows)


def load_dominant_genre() -> tuple[dict[str, tuple[str, float]], dict[str, int]]:
    """Dominant genre per tag, from the artists' *other* evidence.

    For every artist carrying the tag, its strongest genre among the other
    tags is taken; the tag's dominant genre is the mode of those, and its
    share measures how much the tag actually determines a genre.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        tags = [r[0] for r in con.execute(
            "select distinct raw_tag from int_artists_tag_scores"
        ).fetchall()]
        rows = con.execute(
            """
            with evidence as (
                select artist_id, discogs_genre, sum(row_weight) as w
                from int_artists_tag_scores
                group by 1, 2
            ),
            carries as (
                select distinct artist_id, raw_tag from int_artists_tag_scores
            )
            select c.raw_tag, e.artist_id, e.discogs_genre, e.w
            from carries c join evidence e using (artist_id)
            """
        ).fetchall()
    finally:
        con.close()

    per_tag: dict[str, dict[str, dict[str, float]]] = {}
    for tag, artist_id, genre, weight in rows:
        per_tag.setdefault(tag, {}).setdefault(artist_id, {})
        per_tag[tag][artist_id][genre] = per_tag[tag][artist_id].get(genre, 0.0) + weight

    dominant: dict[str, tuple[str, float]] = {}
    others: dict[str, int] = {}
    for tag in tags:
        artists = per_tag.get(tag, {})
        others[tag] = len(artists)
        if not artists:
            continue
        votes: dict[str, int] = {}
        for genres in artists.values():
            best = max(genres.items(), key=lambda kv: kv[1])[0]
            votes[best] = votes.get(best, 0) + 1
        top, n = max(votes.items(), key=lambda kv: kv[1])
        dominant[tag] = (top, n / len(artists))
    return dominant, others


def ambiguous_key_tags(seed: dict[str, dict], _genres, _exact, ambiguous: set) -> list[str]:
    """Tags whose normalized tokens contain one of the ambiguous taxonomy keys."""
    hits = []
    for tag, row in seed.items():
        if row["is_genre_tag"] != "true":
            continue
        tokens = ct.normalize(tag).split()
        for key in ambiguous:
            ktoks = key.split()
            if len(ktoks) <= len(tokens) and any(
                tokens[i:i + len(ktoks)] == ktoks for i in range(len(tokens) - len(ktoks) + 1)
            ):
                hits.append(tag)
                break
    return hits


MIN_OTHER_ARTISTS = 10


def build(top: int, ambiguous_n: int, random_n: int, seed_value: int) -> list[dict]:
    genres, exact_index, ambiguous = ct.load_taxonomy()
    seed_rows = load_seed()
    usage = load_usage()
    dominant, others = load_dominant_genre()

    genre_tags = [t for t, r in seed_rows.items() if r["is_genre_tag"] == "true"]
    ranked = sorted(genre_tags, key=lambda t: (-usage.get(t, 0), t))

    chosen: list[str] = []
    strata: dict[str, str] = {}

    for tag in ranked[:top]:
        chosen.append(tag)
        strata[tag] = "top"

    amb = sorted(
        (t for t in ambiguous_key_tags(seed_rows, genres, exact_index, ambiguous)
         if t not in strata),
        key=lambda t: (-usage.get(t, 0), t),
    )
    for tag in amb[:ambiguous_n]:
        chosen.append(tag)
        strata[tag] = "ambiguous"

    remaining = [t for t in ranked if t not in strata]
    rng = random.Random(seed_value)
    for tag in rng.sample(remaining, min(random_n, len(remaining))):
        chosen.append(tag)
        strata[tag] = "random"

    rows = []
    for tag in sorted(chosen):
        row = seed_rows[tag]
        note = ""
        dom = dominant.get(tag)
        if others.get(tag, 0) < MIN_OTHER_ARTISTS:
            note = ""
        elif dom is None:
            note = "no other evidence to compare against"
        else:
            genre, share = dom
            if share < WEAK_SHARE:
                note = f"no dominant genre (top share {share:.2f}: {genre})"
            elif genre != row["discogs_genre"]:
                note = f"data suggests {genre} (share {share:.2f}) instead of {row['discogs_genre']}"
        rows.append({
            "raw_tag": tag,
            "is_genre_tag": row["is_genre_tag"],
            "discogs_genre": row["discogs_genre"],
            "discogs_style": row["discogs_style"],
            "usage_artists": usage.get(tag, 0),
            "current_match_method": row["match_method"],
            "note": note,
        })
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=40, help="highest-usage tags")
    parser.add_argument("--ambiguous", type=int, default=30, help="tags carrying an ambiguous key")
    parser.add_argument("--random", type=int, default=80, help="random draw from the rest")
    parser.add_argument("--seed", type=int, default=42, help="random seed (reproducible draw)")
    parser.add_argument("--out", type=Path, default=GOLD_CSV)
    args = parser.parse_args(argv)

    rows = build(args.top, args.ambiguous, args.random, args.seed)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)

    flagged = sum(1 for r in rows if r["note"])
    print(f"wrote {args.out} ({len(rows)} tags)")
    print(f"  {args.top} highest-usage, {args.ambiguous} ambiguous, {args.random} random")
    print(f"  {flagged} rows carry a note worth reviewing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
