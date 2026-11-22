#!/usr/bin/env python3
"""Find tags whose classification disagrees with the artists' own context.

For every tag, compare the genre it was assigned with the dominant genre of
the *other* tags carried by the same artists. A tag used by many artists
that almost all point elsewhere is a strong error candidate: a hundred
artists cannot all be wrong, but one heuristic can.

This is what caught "jazz beats -> Jazz" (its 100 artists are Hip Hop 79%),
"punk rap -> Rock / Punk" (Hip Hop 90%) and "cinematic classical ->
Classical" (Stage & Screen 68%). It found more errors in the containment
layer than any model change would have.

Important: the metric is *internal consistency*, not accuracy. A tag can be
correctly classified and still disagree with an artist's other tags, because
artists genuinely span genres. Two consequences:

  * it is only meaningful for a *specific tag* with enough artists, not as a
    per-method average (that would punish artists who legitimately span
    genres, and would suggest cutting the weight of exact matches, which are
    correct by construction);
  * exact and alias matches are the taxonomy's own answer, so they are
    excluded by default: a low score there describes the library, not a bug.

Usage::

    python scripts/classifier/context_audit.py
    python scripts/classifier/context_audit.py --min-artists 20 --max-agreement 0.3
    python scripts/classifier/context_audit.py --include-exact --out review.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
SEED_CSV = ROOT / "seeds" / "tag_genre_map.csv"
DB_PATH = ROOT / "data" / "spotify.duckdb"

HEURISTIC_METHODS = {"fuzzy", "llm"}


def load_seed(path: Path = SEED_CSV) -> dict[str, dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return {row["raw_tag"]: row for row in csv.DictReader(f)}


def context_agreement(con: duckdb.DuckDBPyConnection, seed: dict[str, dict]) -> dict[str, dict]:
    """Per tag: agreement with the dominant genre of the artists' other tags."""
    rows = con.execute(
        "select artist_id, raw_tag, row_weight from int_artists_tag_scores"
    ).fetchall()

    by_artist: dict[str, list[tuple[str, float]]] = defaultdict(list)
    usage: dict[str, set] = defaultdict(set)
    for artist_id, raw_tag, weight in rows:
        by_artist[artist_id].append((raw_tag, weight))
        usage[raw_tag].add(artist_id)

    out: dict[str, dict] = {}
    for raw_tag, row in seed.items():
        if row["is_genre_tag"] != "true":
            continue
        artists = usage.get(raw_tag)
        if not artists:
            continue
        agree = 0
        total = 0
        tally: Counter = Counter()
        for artist_id in artists:
            votes: Counter = Counter()
            for tag, weight in by_artist[artist_id]:
                if tag == raw_tag:
                    continue
                votes[seed[tag]["discogs_genre"]] += weight
            if not votes:
                continue
            top = votes.most_common(1)[0][0]
            total += 1
            tally[top] += 1
            if top == row["discogs_genre"]:
                agree += 1
        if not total:
            continue
        out[raw_tag] = {
            "assigned": row["discogs_genre"],
            "style": row["discogs_style"],
            "method": row["match_method"],
            "artists": len(artists),
            "compared": total,
            "agreement": agree / total,
            "context": tally.most_common(3),
        }
    return out


def offenders(
    stats: dict[str, dict],
    min_artists: int = 10,
    max_agreement: float = 0.4,
    methods: set[str] | None = None,
) -> list[tuple[str, dict]]:
    """Tags whose context disagrees *and* points at a different genre.

    The second condition matters: with enough genres in play an artist's
    plurality can land below the threshold while still being the assigned
    genre, which says nothing about the classification.
    """
    methods = HEURISTIC_METHODS if methods is None else methods
    found = [
        (tag, s) for tag, s in stats.items()
        if s["method"] in methods
        and s["artists"] >= min_artists
        and s["agreement"] < max_agreement
        and s["context"]
        and s["context"][0][0] != s["assigned"]
    ]
    return sorted(found, key=lambda kv: (kv[1]["agreement"], -kv[1]["artists"]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--seed", type=Path, default=SEED_CSV)
    parser.add_argument("--min-artists", type=int, default=10)
    parser.add_argument("--max-agreement", type=float, default=0.4)
    parser.add_argument("--include-exact", action="store_true",
                        help="also list exact/alias matches (low scores there describe the library)")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--out", type=Path, default=None, help="write the candidates as CSV")
    args = parser.parse_args(argv)

    seed = load_seed(args.seed)
    con = duckdb.connect(str(args.db), read_only=True)
    try:
        stats = context_agreement(con, seed)
    finally:
        con.close()

    methods = None if args.include_exact else HEURISTIC_METHODS
    found = offenders(stats, args.min_artists, args.max_agreement, methods)

    scope = "all methods" if args.include_exact else "heuristic methods only (fuzzy, llm)"
    print(f"scored tags: {len(stats)}   {scope}")
    print(f"candidates (>= {args.min_artists} artists, < {args.max_agreement:.0%} agreement): {len(found)}\n")

    print(f"{'tag':34}{'assigned':24}{'meth':8}{'art':>5}{'agr':>6}  context")
    for tag, s in found[: args.limit]:
        ctx = "  ".join(f"{g} {c / s['compared']:.0%}" for g, c in s["context"])
        print(f"{tag[:33]:34}{s['assigned'][:23]:24}{s['method']:8}{s['artists']:>5}"
              f"{s['agreement']:>6.0%}  {ctx}")

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["raw_tag", "assigned_genre", "assigned_style", "match_method",
                             "artists", "compared", "agreement",
                             "context_1", "context_1_share",
                             "context_2", "context_2_share"])
            for tag, s in found:
                ctx = s["context"] + [("", "")] * (2 - len(s["context"]))
                writer.writerow([
                    tag, s["assigned"], s["style"], s["method"], s["artists"], s["compared"],
                    f"{s['agreement']:.4f}",
                    ctx[0][0], f"{ctx[0][1] / s['compared']:.4f}" if ctx[0][0] else "",
                    ctx[1][0], f"{ctx[1][1] / s['compared']:.4f}" if ctx[1][0] else "",
                ])
        print(f"\nwrote {args.out} ({len(found)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
