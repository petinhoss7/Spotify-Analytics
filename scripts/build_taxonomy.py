#!/usr/bin/env python3
"""Build the closed Discogs genre/style taxonomy from several sources.

The taxonomy is reference data: the classifier may only answer with values
from it, and the dbt tests check referential integrity against it. It must
therefore be built explicitly rather than hand-edited, so that its
provenance and completeness are auditable.

Sources are merged, never replaced: the Discogs style list evolves and no
single export is complete. A build from 2022 and one from another snapshot
each miss styles the other has (e.g. the 2022 export lacks "Deep Funk" and
"Detroit Techno" while the older local file lacked "Lo-Fi", "Lounge" and
"Jangle Pop").

Rules:

  * union of every (genre, style) pair from every source, so nothing that is
    currently used can become invalid;
  * one spelling per style: styles are grouped by their normalized form and
    the first spelling wins, in source priority order (the local file first,
    so existing labels are never silently renamed);
  * a style whose name is a *different* genre's name is dropped: "Hip Hop"
    and "Latin" appear as styles under Electronic in one export, which would
    make the tags "hip hop" and "latin" ambiguous and send them to the LLM
    instead of resolving them deterministically. A genre that is its own
    style ("Reggae" under Reggae, "Classical" under Classical) is kept.

Usage::

    python scripts/build_taxonomy.py
    python scripts/build_taxonomy.py --source seeds/other_export.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "seeds" / "discogs_genres_styles.json"
CSV_PATH = ROOT / "seeds" / "discogs_genre_styles.csv"
DEFAULT_SOURCES = [
    ROOT / "seeds" / "discogs_genres_styles_quantixed.csv",
    # deliberate local additions on top of the upstream exports. Kept in a
    # separate file so the deviation from Discogs stays explicit and the
    # upstream exports remain untouched.
    ROOT / "seeds" / "discogs_genres_styles_local.csv",
]


def normalize(value: str) -> str:
    """Same folding as the classifier, so the build sees what it will see."""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def read_base(path: Path) -> dict[str, list[str]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["genres"]


def read_source(path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            genre = (row.get("Genre") or row.get("genre") or "").strip()
            style = (row.get("Style") or row.get("style") or "").strip()
            if genre and style:
                pairs.append((genre, style))
    return pairs


def build(base: dict[str, list[str]], sources: list[Path]) -> tuple[dict[str, list[str]], dict]:
    genre_names = {normalize(g) for g in base}

    # spelling per normalized style, in priority order: base first, then sources
    spelling: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    for genre, styles in base.items():
        for style in styles:
            key = normalize(style)
            spelling.setdefault(key, style)
            pairs.append((genre, style))
    for path in sources:
        for genre, style in read_source(path):
            key = normalize(style)
            spelling.setdefault(key, style)
            pairs.append((genre, style))

    merged: dict[str, set[str]] = defaultdict(set)
    dropped: list[tuple[str, str, str]] = []
    renames: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()

    for genre, style in pairs:
        # drop a style named after a different genre (see module docstring)
        if normalize(style) in genre_names and normalize(style) != normalize(genre):
            dropped.append((genre, style, "style name is another genre's name"))
            continue
        canonical = spelling[normalize(style)]
        if canonical != style:
            renames[style] = canonical
        key = (genre, canonical)
        if key in seen:
            continue
        seen.add(key)
        merged[genre].add(canonical)

    result = {genre: sorted(styles) for genre, styles in sorted(merged.items())}
    meta = {
        "genres": len(result),
        "styles": sum(len(v) for v in result.values()),
        "pairs": sum(len(v) for v in result.values()),
        "dropped": [f"{g} | {s} ({why})" for g, s, why in dropped],
    }
    return result, meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=JSON_PATH)
    parser.add_argument("--source", type=Path, action="append", default=None)
    parser.add_argument("--json", type=Path, default=JSON_PATH)
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    args = parser.parse_args(argv)

    sources = args.source if args.source is not None else DEFAULT_SOURCES
    base = read_base(args.base)
    genres, meta = build(base, sources)

    before = {g: set(v) for g, v in base.items()}
    added = {g: sorted(set(genres.get(g, [])) - before.get(g, set())) for g in genres}
    n_added = sum(len(v) for v in added.values())

    document = {
        "meta": {
            "source": "Discogs Database Guidelines - Genres & Styles (merged)",
            "built_at": date.today().isoformat(),
            "sources": ["seeds/discogs_genres_styles.json"]
                       + [str(p.relative_to(ROOT)).replace("\\", "/") for p in sources],
            "note": "Closed reference list. Built by scripts/build_taxonomy.py - do not "
                    "hand-edit: edit the sources and rebuild.",
            "structure": "genre -> list of allowed styles (sub-genres)",
            "counts": {"genres": meta["genres"], "styles": meta["styles"]},
            "dropped": meta["dropped"],
        },
        "genres": genres,
    }
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=2)
        f.write("\n")

    rows = []
    for genre in sorted(genres):
        rows.append((genre, ""))          # genre with no style
        for style in sorted(genres[genre]):
            rows.append((genre, style))
    with open(args.csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["discogs_genre", "discogs_style"])
        writer.writerows(rows)

    print(f"genres: {meta['genres']}  styles: {meta['styles']}  "
          f"(csv rows: {len(rows)}, incl. {meta['genres']} genre-only)")
    print(f"styles added by this build: {n_added}")
    for genre in sorted(added):
        if added[genre]:
            print(f"  + {genre}: {len(added[genre])}")
    if meta["dropped"]:
        print("dropped (style named after a different genre):")
        for line in meta["dropped"]:
            print(f"  - {line}")
    print(f"wrote {args.json}")
    print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
