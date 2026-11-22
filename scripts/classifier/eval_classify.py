#!/usr/bin/env python3
"""Score the current classification against the reviewed gold set.

The gold set (seeds/tag_gold.csv) is the arbiter for every change to the
classifier: without it, swapping a model or promoting a layer is just
replacing one black box with another. This script is the gate.

Comparison is exact on (is_genre_tag, discogs_genre, discogs_style).
Nothing here needs DuckDB or the network, so it runs anywhere, including
CI, and can be run on any candidate seed file.

Usage::

    python scripts/classifier/eval_classify.py
    python scripts/classifier/eval_classify.py --seed seeds/tag_genre_map.csv
    python scripts/classifier/eval_classify.py --min-accuracy 0.90

Exit codes: 0 above the threshold, 1 below (or a gold tag missing from
the seed). A pristine, not-yet-reviewed gold set scores 1.0 and warns.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD_CSV = ROOT / "seeds" / "tag_gold.csv"
SEED_CSV = ROOT / "seeds" / "tag_genre_map.csv"

HIGH_USAGE = 20


def read_rows(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return {row["raw_tag"]: row for row in csv.DictReader(f)}


def as_bool(value: str) -> bool:
    return (value or "").strip().lower() == "true"


def norm_field(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def compare(gold: dict, seed: dict) -> list[str]:
    problems = []
    if as_bool(gold["is_genre_tag"]) != as_bool(seed["is_genre_tag"]):
        problems.append("is_genre_tag")
        return problems
    if not as_bool(gold["is_genre_tag"]):
        return problems
    if norm_field(gold["discogs_genre"]) != norm_field(seed["discogs_genre"]):
        problems.append("discogs_genre")
    if norm_field(gold["discogs_style"]) != norm_field(seed["discogs_style"]):
        problems.append("discogs_style")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=GOLD_CSV)
    parser.add_argument("--seed", type=Path, default=SEED_CSV)
    parser.add_argument("--min-accuracy", type=float, default=0.85,
                        help="fail below this accuracy (default 0.85)")
    parser.add_argument("--max-errors", type=int, default=40, help="errors to print")
    args = parser.parse_args(argv)

    gold_rows = read_rows(args.gold)
    seed_rows = read_rows(args.seed)

    total = len(gold_rows)
    errors: list[tuple[str, dict, dict, list[str]]] = []
    missing: list[str] = []
    by_method: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_usage: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    reviewed = 0
    for tag, gold in gold_rows.items():
        seed = seed_rows.get(tag)
        if seed is None:
            missing.append(tag)
            continue
        problems = compare(gold, seed)
        method = seed.get("match_method") or "?"
        try:
            usage = int(gold.get("usage_artists") or 0)
        except ValueError:
            usage = 0
        bucket = f"usage>={HIGH_USAGE}" if usage >= HIGH_USAGE else f"usage<{HIGH_USAGE}"
        for counter in (by_method[method], by_usage[bucket]):
            counter[1] += 1
        if problems:
            errors.append((tag, gold, seed, problems))
        else:
            by_method[method][0] += 1
            by_usage[bucket][0] += 1
    noted = sum(1 for g in gold_rows.values() if (g.get("note") or "").strip())

    ok = total - len(errors) - len(missing)
    accuracy = ok / total if total else 0.0

    print(f"gold set: {total} tags ({args.gold})")
    print(f"seed:     {args.seed}")
    print(f"checked:  {total - len(missing)}   missing from seed: {len(missing)}")
    print(f"accuracy: {ok}/{total - len(missing)} = {accuracy:.1%}")
    print()

    print("accuracy by classification method")
    for method, (good, n) in sorted(by_method.items(), key=lambda kv: -kv[1][1]):
        print(f"  {method:8} {good:>4}/{n:<4} {good / n:.1%}")
    print()
    print("accuracy by tag usage")
    for bucket, (good, n) in sorted(by_usage.items()):
        print(f"  {bucket:12} {good:>4}/{n:<4} {good / n:.1%}")

    if errors:
        print(f"\nerrors ({len(errors)}):")
        for tag, gold, seed, problems in errors[: args.max_errors]:
            print(f"  {tag!r} [{seed.get('match_method')}] fields: {', '.join(problems)}")
            print(f"      gold: genre={norm_field(gold['discogs_genre'])!r} style={norm_field(gold['discogs_style'])!r} "
                  f"is_genre={gold['is_genre_tag']}")
            print(f"      seed: genre={norm_field(seed['discogs_genre'])!r} style={norm_field(seed['discogs_style'])!r} "
                  f"is_genre={seed['is_genre_tag']}")
            if (gold.get("note") or "").strip():
                print(f"      note: {gold['note']}")
        if len(errors) > args.max_errors:
            print(f"  ... {len(errors) - args.max_errors} more")

    if missing:
        print(f"\nmissing from the seed ({len(missing)}): {', '.join(missing[:20])}")

    if not errors and not missing:
        print("\n[warn] no gold row disagrees with the seed: the gold set has not been "
              "reviewed yet, so this 100% is vacuous. Edit seeds/tag_gold.csv to "
              "record your decisions (fix the label, or write in `note`).\n"
              f"       {len(gold_rows)} rows, of which {noted} "
              "carry a data-derived note worth a look.")

    if missing or accuracy < args.min_accuracy:
        print(f"\nFAIL: accuracy {accuracy:.1%} < threshold {args.min_accuracy:.1%}"
              + (f", {len(missing)} gold tags missing" if missing else ""))
        return 1
    print(f"\nOK: accuracy {accuracy:.1%} >= threshold {args.min_accuracy:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
