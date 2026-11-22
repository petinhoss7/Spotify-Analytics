#!/usr/bin/env python3
"""Turn the hand-verified review into an applied reference.

Reads seeds/tags_to_verify.csv (the reviewer's verdicts) and writes
seeds/tag_verified.csv, which the classifier applies before every automatic
layer. Nothing is invented: a verdict is only applied if it is expressible
in the closed taxonomy, and anything that cannot be resolved is reported
instead of guessed.

Verdict conventions:

  verdict=ok    keep the classification as it is now
  verdict=nok   apply correct_genre / correct_style, where

      correct_genre = "non-genre"      the tag is not a genre at all
      correct_genre = a genre name     correct_style must belong to it
      correct_genre = a style name     resolved to its parent genre (and
                                       reported, since the column asks for
                                       a genre)

Two cases are resolved by an explicit, auditable DECISIONS table rather
than guessed: a `nok` with no genre filled in, and a `nok` whose approved
value changed since the review because the taxonomy was rebuilt.

Usage::

    python scripts/classifier/apply_verdicts.py
    python scripts/classifier/apply_verdicts.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW_CSV = ROOT / "seeds" / "tags_to_verify.csv"
SEED_CSV = ROOT / "seeds" / "tag_genre_map.csv"
TAXONOMY = ROOT / "seeds" / "discogs_genres_styles.json"
OUT_CSV = ROOT / "seeds" / "tag_verified.csv"

NON_GENRE = "non-genre"

# Explicit resolutions for the cases the review left open. Each entry states
# what was decided and why, so it can be reviewed and changed in one place.
DECISIONS: dict[str, tuple[str, str | None, str | None, str]] = {
    # raw_tag: (kind, genre, style, reason)
    "indie": (
        "non-genre", None, None,
        "reviewer left it undecided ('indie's genre should be either Pop, rock'). "
        "Treated as non-genre, consistently with the other pure modifiers the same "
        "review rejected: dance, progressive, oldies, acoustic, easy listening.",
    ),
}

HEADER = ["raw_tag", "is_genre_tag", "discogs_genre", "discogs_style", "comment"]


def load_taxonomy() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    with open(TAXONOMY, encoding="utf-8") as f:
        genres = json.load(f)["genres"]
    home: dict[str, list[str]] = {}
    for genre, styles in genres.items():
        for style in styles:
            home.setdefault(style, []).append(genre)
    return genres, home


def read_review() -> list[dict]:
    with open(REVIEW_CSV, encoding="utf-8", newline="") as f:
        return [row for row in csv.DictReader(f)]


def read_seed() -> dict[str, dict]:
    with open(SEED_CSV, encoding="utf-8", newline="") as f:
        return {row["raw_tag"]: row for row in csv.DictReader(f)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT_CSV)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    genres, style_home = load_taxonomy()
    review = read_review()
    seed = read_seed()

    verified: list[dict] = []
    problems: list[str] = []
    notes: list[str] = []
    counts = {"ok": 0, "non-genre": 0, "genre": 0, "unresolved": 0, "unchanged": 0}

    for row in review:
        tag = row["raw_tag"]
        verdict = (row.get("verdict") or "").strip().lower()
        current = seed.get(tag)
        if current is None:
            problems.append(f"{tag!r}: absent from the current seed")
            continue

        if verdict not in {"ok", "nok"}:
            problems.append(f"{tag!r}: verdict {verdict!r} is neither ok nor nok")
            continue

        current_genre = current["discogs_genre"] or None
        current_style = current["discogs_style"] or None

        if verdict == "ok":
            # the approved value may have changed since the review, because the
            # taxonomy was rebuilt in between; say so instead of hiding it
            if (current_genre, current_style) != (
                (row.get("current_genre") or None), (row.get("current_style") or None)
            ):
                notes.append(
                    f"{tag!r}: approved as {row.get('current_genre') or '-'} / "
                    f"{row.get('current_style') or '-'} but now classified "
                    f"{current_genre or '-'} / {current_style or '-'} - kept the new value"
                )
            genre, style, is_genre = current_genre, current_style, current["is_genre_tag"] == "true"
            counts["ok"] += 1
            if not is_genre:
                counts["unchanged"] += 1
        else:
            raw_genre = (row.get("correct_genre") or "").strip()
            raw_style = (row.get("correct_style") or "").strip() or None

            if not raw_genre and tag in DECISIONS:
                kind, genre, style, _reason = DECISIONS[tag]
                is_genre = kind != "non-genre"
                notes.append(f"{tag!r}: {DECISIONS[tag][3]}")
            elif raw_genre.lower() == NON_GENRE:
                is_genre, genre, style = False, None, None
                counts["non-genre"] += 1
            elif raw_genre in genres:
                is_genre, genre, style = True, raw_genre, raw_style
                if style and style not in genres[genre]:
                    problems.append(f"{tag!r}: style {style!r} is not under genre {genre!r}")
                    counts["unresolved"] += 1
                    continue
                counts["genre"] += 1
            elif raw_genre in style_home:
                parents = style_home[raw_genre]
                is_genre, genre, style = True, parents[0], raw_genre
                notes.append(
                    f"{tag!r}: {raw_genre!r} is a style, not a genre; resolved to "
                    f"{parents[0]!r} / {raw_genre!r}"
                )
                counts["genre"] += 1
            elif not raw_genre:
                problems.append(f"{tag!r}: nok with no correct_genre - left as classified")
                counts["unresolved"] += 1
                continue
            else:
                problems.append(f"{tag!r}: correct_genre {raw_genre!r} is not in the taxonomy")
                counts["unresolved"] += 1
                continue

        comment = (row.get("comment") or "").strip()
        if tag in DECISIONS and not comment:
            comment = DECISIONS[tag][3]
        verified.append({
            "raw_tag": tag,
            "is_genre_tag": "true" if is_genre else "false",
            "discogs_genre": genre or "",
            "discogs_style": style or "",
            "comment": comment,
        })

    changed = 0
    for v in verified:
        cur = seed.get(v["raw_tag"])
        if cur and (
            v["is_genre_tag"] != cur["is_genre_tag"]
            or v["discogs_genre"] != (cur["discogs_genre"] or "")
            or v["discogs_style"] != (cur["discogs_style"] or "")
        ):
            changed += 1

    print(f"review rows: {len(review)}")
    print(f"  ok: {counts['ok']} (of which already non-genre: {counts['unchanged']})")
    print(f"  nok -> non-genre: {counts['non-genre']}")
    print(f"  nok -> genre/style: {counts['genre']}")
    print(f"  unresolved (kept as classified): {counts['unresolved']}")
    print(f"\nverified rows: {len(verified)}")
    print(f"  of which change the current classification: {changed}")

    if notes:
        print(f"\nresolutions and drift ({len(notes)}):")
        for n in notes:
            print(f"  - {n}")
    if problems:
        print(f"\nproblems ({len(problems)}):")
        for p in problems:
            print(f"  ! {p}")

    if args.dry_run:
        print("\n[dry run] nothing written")
        return 0

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(verified)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
