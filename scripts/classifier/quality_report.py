#!/usr/bin/env python3
"""Quality report for the genre classification and attribution.

Reads the built DuckDB warehouse and prints the metrics used to judge
whether a change to the classification improved things:

  1. attributed artists, and how many remain unclassified
  2. primary-genre distribution and the Electronic concentration
  3. confirmation rate against MusicBrainz *structured* genres - an
     independent label source never fed into the classifier, so it acts
     as a referee for the tag-based attributions
  4. cross-source agreement (Jaccard) between lastfm / musicbrainz /
     rapidapi tag sets
  5. how much evidence is hedged (confidence < 1) by tag_overrides.csv

Usage::

    python scripts/classifier/quality_report.py
    python scripts/classifier/quality_report.py --json out.json

Exit code is always 0: this is an observation tool, not a gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify_tags as ct  # noqa: E402

DB_PATH = ROOT / "data" / "spotify.duckdb"


def pct(numerator: float, denominator: float) -> str:
    return f"{numerator / denominator:.1%}" if denominator else "n/a"


def build_musicbrainz_genre_sets(con: duckdb.DuckDBPyConnection) -> dict[str, set[str]]:
    """Discogs genre sets derived from MusicBrainz's structured `genres` field.

    This field is deliberately absent from the classifier's inputs: it is
    used here only as an external referee.
    """
    genres, exact_index, ambiguous = ct.load_taxonomy()
    entries = ct.build_containment_index(exact_index, genres)
    aliases = ct.load_aliases(ct.ALIASES_PATH, genres, exact_index, ambiguous)
    map_rows = dict(
        con.execute(
            "select raw_tag, discogs_genre from tag_genre_map where is_genre_tag"
        ).fetchall()
    )

    def to_genre(name: str) -> str | None:
        key = name.strip().lower()
        if key in map_rows:
            return map_rows[key]
        hit = ct.static_classify(ct.normalize(key), exact_index, aliases, entries, ambiguous)
        return hit[0][0] if hit else None

    sets: dict[str, set[str]] = {}
    rows = con.execute(
        """
        select artist_id, genres
        from raw.raw_musicbrainz_artists
        where genres is not null and trim(genres) <> '[]'
        """
    ).fetchall()
    for artist_id, raw in rows:
        found = set()
        for item in json.loads(raw):
            name = item if isinstance(item, str) else (item.get("name") or "")
            if not name:
                continue
            genre = to_genre(name)
            if genre:
                found.add(genre)
        if found:
            sets[artist_id] = found
    return sets


def report(con: duckdb.DuckDBPyConnection) -> dict:
    out: dict = {}

    total_artists = con.execute("select count(*) from int_artists").fetchone()[0]
    attributed = con.execute(
        "select count(*) from int_artists_genre_attribution"
    ).fetchone()[0]
    out["artists"] = {
        "total": total_artists,
        "attributed": attributed,
        "unclassified": total_artists - attributed,
        "unclassified_rate": round((total_artists - attributed) / total_artists, 4),
    }

    primaries = con.execute(
        """
        select primary_genre, count(*) as n
        from int_artists_genre_attribution
        group by 1 order by n desc
        """
    ).fetchall()
    out["primary_genres"] = {
        genre: {"artists": n, "share": round(n / attributed, 4)} for genre, n in primaries
    }
    top_genre, top_n = primaries[0]
    out["primary_genres"]["_concentration"] = {
        "top_genre": top_genre,
        "share": round(top_n / attributed, 4),
    }

    mb_sets = build_musicbrainz_genre_sets(con)
    primary = dict(
        con.execute(
            "select artist_id, primary_genre from int_artists_genre_attribution"
        ).fetchall()
    )
    comparable = [a for a in mb_sets if a in primary]
    confirmed = [a for a in comparable if primary[a] in mb_sets[a]]
    out["musicbrainz_confirmation"] = {
        "artists_with_mb_genres": len(mb_sets),
        "comparable": len(comparable),
        "confirmed": len(confirmed),
        "rate": round(len(confirmed) / len(comparable), 4) if comparable else None,
    }

    agreement = con.execute(
        """
        select count(*) as artists,
               round(avg(agreement_score), 4) as mean_genre_jaccard,
               round(avg(subgenre_agreement_score), 4) as mean_style_jaccard,
               sum(case when agreement_score < 0.5 then 1 else 0 end) as low_agreement
        from int_source_tag_cross_comparison
        """
    ).fetchone()
    out["cross_source_agreement"] = {
        "artists_compared": agreement[0],
        "mean_genre_jaccard": agreement[1],
        "mean_style_jaccard": agreement[2],
        "artists_below_0_5": agreement[3],
    }

    rows_by_method = con.execute(
        """
        select match_method, count(*) as n
        from int_source_tag_classification
        group by 1 order by n desc
        """
    ).fetchall()
    hedged = con.execute(
        """
        select count(*)
        from int_source_tag_classification
        where classification_status = 'genre' and coalesce(confidence, 1.0) < 1.0
        """
    ).fetchone()[0]
    genre_rows = sum(n for m, n in rows_by_method if m != "noise")
    out["evidence"] = {
        "genre_tag_rows": genre_rows,
        "hedged_genre_rows": hedged,
        "hedged_share": round(hedged / genre_rows, 4) if genre_rows else None,
        "tag_rows_by_method": {m: n for m, n in rows_by_method},
    }

    out["seed_methods"] = dict(
        con.execute(
            "select match_method, count(*) from tag_genre_map group by 1 order by 2 desc"
        ).fetchall()
    )
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--json", type=Path, default=None, help="also write the metrics as JSON")
    args = parser.parse_args(argv)

    con = duckdb.connect(str(args.db), read_only=True)
    try:
        metrics = report(con)
    finally:
        con.close()

    artists = metrics["artists"]
    print("=== attribution coverage ===")
    print(f"  artists: {artists['total']}  attributed: {artists['attributed']}  "
          f"unclassified: {artists['unclassified']} ({artists['unclassified_rate']:.1%})")

    print("\n=== primary genres ===")
    concentration = metrics["primary_genres"].pop("_concentration")
    for genre, stats in metrics["primary_genres"].items():
        print(f"  {genre:26} {stats['artists']:>5}  {stats['share']:.1%}")
    print(f"  -> most concentrated: {concentration['top_genre']} {concentration['share']:.1%}")

    mb = metrics["musicbrainz_confirmation"]
    print("\n=== MusicBrainz structured-genre confirmation ===")
    print(f"  comparable artists: {mb['comparable']}  confirmed: {mb['confirmed']}  "
          f"rate: {mb['rate']:.1%}" if mb["rate"] is not None else "  no data")

    agreement = metrics["cross_source_agreement"]
    print("\n=== cross-source agreement ===")
    print(f"  artists compared: {agreement['artists_compared']}  "
          f"mean genre Jaccard: {agreement['mean_genre_jaccard']}  "
          f"mean style Jaccard: {agreement['mean_style_jaccard']}")
    print(f"  below 0.5: {agreement['artists_below_0_5']} "
          f"({pct(agreement['artists_below_0_5'], agreement['artists_compared'])})")

    evidence = metrics["evidence"]
    print("\n=== evidence mix ===")
    for method, n in sorted(evidence["tag_rows_by_method"].items(), key=lambda kv: -kv[1]):
        print(f"  {str(method):12} {n:>7}")
    print(f"  hedged genre rows: {evidence['hedged_genre_rows']} "
          f"({evidence['hedged_share']:.1%} of genre rows)")

    print("\n=== seed (tag_genre_map) ===")
    for method, n in sorted(metrics["seed_methods"].items(), key=lambda kv: -kv[1]):
        print(f"  {method:8} {n:>6}")

    if args.json:
        args.json.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
