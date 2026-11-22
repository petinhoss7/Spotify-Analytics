#!/usr/bin/env python3
"""Classify raw music tags into the closed Discogs genre/style taxonomy.

Layers:
  L0 overrides    seeds/tag_overrides.csv, human-curated, always wins
  L0 normalize    lowercase, strip accents/punctuation, & -> and
  L1 exact        normalized tag == normalized closed-list key
  L2 alias        seeds/tag_aliases.csv rewrite (one hop) then L1
  L3 containment  closed-list key found as whole consecutive tokens in the
                  tag (longest key wins); replaces naive string similarity,
                  which cannot separate "old school thrash"->Thrash from
                  garbage like "draincore"->Rai at any threshold
  L4 llm          OpenRouter chat completion, closed list in system prompt
  review          failures parked to logs/classifier/review_pending.csv

Confidence model (two independent factors, multiplied in dbt):

  match_method -> method_weight   reliability of the *mechanism*
      manual / exact / alias 1.0, fuzzy 0.9, llm 0.8
      (derived in dbt from match_method, not stored in the seed)
  confidence   -> specificity    reliability of the *tag meaning*
      written here as 1.0 for every automatic layer; only the curated
      overrides lower it, for generic tags that do not determine a genre
      by themselves ("dance", "indie", "oldies"...) so that an artist's
      real genre tags always outrank them

  row_weight = method_weight x confidence x ln(1 + tag_count)

Outputs:
  seeds/tag_genre_map.csv    raw_tag, is_genre_tag, discogs_genre, discogs_style, match_method, match_score, confidence
  data/tag_llm_cache.json    L4 response cache (resumable, re-runs are free)
  logs/classifier/           run logs + review file

Exit codes: 0 ok, 1 fail-fast build error, 2 clean abort (circuit open / missing key, resumable), 130 interrupted.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
EXTRACTS = ROOT / "extracts"
SEEDS = ROOT / "seeds"
LOGS = ROOT / "logs" / "classifier"
DATA = ROOT / "data"
TAXONOMY_PATH = SEEDS / "discogs_genres_styles.json"
ALIASES_PATH = SEEDS / "tag_aliases.csv"
OVERRIDES_PATH = SEEDS / "tag_overrides.csv"
DB_PATH = DATA / "spotify.duckdb"
DEFAULT_CACHE = DATA / "tag_llm_cache.json"

EXTRACT_FILES = ["lastfm_export.csv", "musicbrainz_export.csv", "rapidapi_export.csv"]
STAGING_TAG_TABLES = [
    "main.stg_lastfm_artists_tags",
    "main.stg_musicbrainz_artists_tags",
    "main.stg_spotify_artists_tags",
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT = (10, 120)
MAX_API_ATTEMPTS = 5
CIRCUIT_THRESHOLD = 3

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 522, 524, 529}


class BuildError(Exception):
    pass


class CircuitOpen(Exception):
    pass


def normalize(s: object) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def load_taxonomy(path: Path = TAXONOMY_PATH):
    with open(path, encoding="utf-8") as f:
        genres = json.load(f)["genres"]
    candidates: dict[str, list] = {}
    for genre, styles in genres.items():
        candidates.setdefault(normalize(genre), []).append((genre, None))
        for style in styles:
            candidates.setdefault(normalize(style), []).append((genre, style))
    exact_index: dict[str, tuple] = {}
    ambiguous: set[str] = set()
    for key, pairs in candidates.items():
        distinct = set(pairs)
        if len(distinct) == 1:
            exact_index[key] = pairs[0]
            continue
        if len({g for g, _ in distinct}) == 1:
            with_style = sorted(p for p in distinct if p[1] is not None)
            exact_index[key] = with_style[0]
        else:
            ambiguous.add(key)
    return genres, exact_index, ambiguous


def load_aliases(path: Path, genres: dict, exact_index: dict, ambiguous: set) -> dict:
    aliases: dict[str, tuple] = {}
    errors: list[str] = []
    if not path.exists():
        return aliases
    with open(path, encoding="utf-8-sig", newline="") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            alias = (row.get("alias") or "").strip()
            target = (row.get("target") or "").strip()
            if not alias or not target:
                errors.append(f"line {lineno}: empty alias or target")
                continue
            akey = normalize(alias)
            if not akey:
                errors.append(f"line {lineno}: alias normalizes to empty: {alias!r}")
                continue
            if akey in aliases:
                errors.append(f"line {lineno}: duplicate alias: {alias!r}")
                continue
            if "|" in target:
                g, _, s = target.partition("|")
                aliases[akey] = ("pair", (g.strip(), s.strip() or None))
            else:
                aliases[akey] = ("term", normalize(target))
    for akey, (kind, val) in aliases.items():
        if kind == "pair":
            g, s = val
            if g not in genres:
                errors.append(f"alias {akey!r}: unknown genre {g!r}")
            elif s and s not in genres[g]:
                errors.append(f"alias {akey!r}: style {s!r} is not under genre {g!r}")
        elif val not in exact_index and val not in ambiguous:
            errors.append(f"alias {akey!r}: target {val!r} is not a closed-list term")
    if errors:
        raise BuildError("tag_aliases.csv is invalid:\n" + "\n".join(errors))
    return aliases


def alias_lookup(tag_norm: str, aliases: dict, exact_index: dict):
    hit = aliases.get(tag_norm)
    if hit is None:
        return None
    kind, val = hit
    if kind == "pair":
        return val
    return exact_index.get(val)


def load_overrides(path: Path, genres: dict) -> dict:
    """Human-curated overrides, applied before every automatic layer.

    Unlike tag_aliases.csv (which rewrites the tag and re-enters L1), an
    override fixes the final answer and its confidence. It is the only place
    where a tag that is *not* a genre can be stripped of a genre label that
    the automatic layers would otherwise invent for it.
    """
    overrides: dict[str, dict] = {}
    errors: list[str] = []
    if not path.exists():
        return overrides
    with open(path, encoding="utf-8-sig", newline="") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            raw = (row.get("raw_tag") or "").strip()
            if not raw or raw.startswith("#"):
                continue
            key = normalize(raw)
            if not key:
                errors.append(f"line {lineno}: raw_tag normalizes to empty: {raw!r}")
                continue
            if key in overrides:
                errors.append(f"line {lineno}: duplicate raw_tag: {raw!r}")
                continue
            flag = (row.get("is_genre_tag") or "").strip().lower()
            if flag not in {"true", "false"}:
                errors.append(f"line {lineno}: is_genre_tag must be true or false, got {flag!r}")
                continue
            is_genre = flag == "true"
            genre = (row.get("discogs_genre") or "").strip() or None
            style = (row.get("discogs_style") or "").strip() or None
            conf_raw = (row.get("confidence") or "").strip()
            try:
                confidence = float(conf_raw) if conf_raw else None
            except ValueError:
                errors.append(f"line {lineno}: confidence is not a number: {conf_raw!r}")
                continue
            if not is_genre:
                if genre or style:
                    errors.append(f"line {lineno}: non-genre override must leave genre/style empty: {raw!r}")
                    continue
            else:
                if genre not in genres:
                    errors.append(f"line {lineno}: unknown genre {genre!r}: {raw!r}")
                    continue
                if style is not None and style not in genres[genre]:
                    errors.append(f"line {lineno}: style {style!r} is not under genre {genre!r}: {raw!r}")
                    continue
                if confidence is None or not 0 < confidence <= 1:
                    errors.append(f"line {lineno}: genre override needs confidence in (0, 1]: {raw!r}")
                    continue
            overrides[key] = {
                "is_genre_tag": is_genre,
                "genre": genre,
                "style": style,
                "confidence": confidence,
                "justification": (row.get("justification") or "").strip(),
                "raw_tag": raw,
            }
    if errors:
        raise BuildError("tag_overrides.csv is invalid:\n" + "\n".join(errors))
    return overrides


# Tag-specificity weight written for every automatic layer. Method
# reliability is derived from match_method in dbt (int_artists_tag_scores),
# so it must NOT be duplicated here: only curated overrides lower it.
DEFAULT_SPECIFICITY = 1.0


CONTAINMENT_SINGLE_TOKEN_ALLOWLIST = {
    "acid", "ambient", "bachata", "ballad", "bassline", "beatdown", "bluegrass",
    "bolero", "boogaloo", "boogie", "bop", "breakbeat", "breakcore", "breaks", "britcore",
    "cajun", "calypso", "celtic", "champeta", "chanson", "chiptune", "choral",
    "crust", "cumbia", "dixieland", "downtempo", "dubstep", "ebm", "eurobeat",
    "eurodance", "flamenco", "fado", "footwork", "fusion", "gabber", "grime",
    "grindcore", "grunge", "halftime", "hardstyle", "hillbilly", "highlife",
    "horrorcore", "house", "idm", "jungle", "krautrock", "laiko", "makina",
    "mambo", "mariachi", "medieval", "merengue", "metalcore", "modal", "norteno",
    "nordic", "opera", "polka", "punk", "ragga", "ragtime", "rai", "reggaeton",
    "rumba", "rockabilly", "rocksteady", "salsa", "samba", "screw", "schlager",
    "schranz", "shoegaze", "soca", "son", "soukous", "surf", "swing", "synthwave",
    "tango", "tejano", "thrash", "trap", "turntablism", "vaporwave", "vallenato",
    "zouk", "funk", "soul", "techno", "trance",
}


def build_containment_index(exact_index: dict, genres: dict) -> list:
    genre_keys = {normalize(g) for g in genres}
    entries = []
    for key, pair in exact_index.items():
        toks = tuple(key.split())
        if len(toks) >= 2 or key in genre_keys or key in CONTAINMENT_SINGLE_TOKEN_ALLOWLIST:
            entries.append((toks, len(toks), key, pair))
    entries.sort(key=lambda e: (-e[1], e[2]))
    return entries


def containment_match(tag_norm: str, entries: list):
    toks = tag_norm.split()
    n = len(toks)
    if not n:
        return None
    hits = []
    for ktoks, klen, _key, pair in entries:
        if hits and klen < hits[0][0]:
            break
        if klen > n:
            continue
        if any(tuple(toks[i : i + klen]) == ktoks for i in range(n - klen + 1)):
            hits.append((klen, pair))
    if not hits:
        return None
    best_len = hits[0][0]
    winners = {pair for klen, pair in hits if klen == best_len}
    if len(winners) != 1:
        return None
    return winners.pop()


def static_classify(
    tag_norm: str,
    exact_index: dict,
    aliases: dict,
    containment_entries: list,
    ambiguous: set = frozenset(),
):
    pair = exact_index.get(tag_norm)
    if pair:
        return pair, "exact", 100
    pair = alias_lookup(tag_norm, aliases, exact_index)
    if pair:
        return pair, "alias", 100
    # A tag that *is* an ambiguous taxonomy key must never be resolved by
    # containment: "rhythm and blues" contains the genre key "blues", but the
    # phrase itself lives under several genres and only L4 (or an explicit
    # alias) may decide it.
    if tag_norm in ambiguous:
        return None
    hit = containment_match(tag_norm, containment_entries)
    if hit:
        return hit, "fuzzy", 90
    return None


def load_extract_vocab() -> set:
    tags = set()
    for name in EXTRACT_FILES:
        path = EXTRACTS / name
        if not path.exists():
            raise BuildError(f"missing extract file: {path}")
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                t = (row.get("tag_name") or "").strip().lower()
                if t:
                    tags.add(t)
    return tags


def load_db_vocab() -> set:
    try:
        import duckdb
        con = duckdb.connect(str(DB_PATH), read_only=True)
    except Exception as exc:
        print(f"[warn] DuckDB unavailable ({exc}); vocabulary from extracts only")
        return set()
    try:
        unions = " UNION ALL ".join(f"SELECT tag_name FROM {t}" for t in STAGING_TAG_TABLES)
        rows = con.execute(
            f"SELECT DISTINCT lower(trim(tag_name)) AS t FROM ({unions}) WHERE t IS NOT NULL AND t <> ''"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


def is_noise(tag_norm: str) -> bool:
    t = tag_norm.replace(" ", "")
    return bool(
        t.isdigit()
        or re.fullmatch(r"[0-9a-f]{8,}", t)
        or re.fullmatch(r"\d{1,4}s", t)
        or len(tag_norm) > 80
    )


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        backup = path.with_suffix(".corrupt.bak")
        os.replace(path, backup)
        print(f"[warn] cache unreadable, moved to {backup}")
        return {}


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


SYSTEM_PROMPT_TEMPLATE = """You classify raw music listener tags into the Discogs genre/style taxonomy.

Rules:
- genre must be exactly one of the genre names in the taxonomy below, or null.
- style must be null, or exactly one of the style names listed under the chosen genre in the taxonomy. Never use a style from another genre.
- If the tag is a musical genre/style: is_genre_tag=true, fill genre, and fill style only when a specific style fits (otherwise null).
- If the tag is NOT a musical genre/style (nationalities, countries, cities, languages, decades/years, "seen live", moods, instruments, vocal types, artist names, labels, formats, events), set is_genre_tag=false, genre=null, style=null.
- If a style name exists under multiple genres, choose the genre matching the tag's most common global musical usage.
- Interpret misspellings, transliterations and non-English tags as music tags when they plausibly refer to a genre (e.g. "chanson francaise" -> Pop/Chanson); otherwise is_genre_tag=false.
- Output strict JSON with no markdown and no commentary, exactly:
{"classifications":[{"tag":"<original tag, copied exactly>","is_genre_tag":true,"genre":"<genre or null>","style":"<style or null>"}]}
- Return exactly one object per input tag, same order as the input.

Taxonomy:
{TAXONOMY}"""


def build_system_prompt(genres: dict) -> str:
    return SYSTEM_PROMPT_TEMPLATE.replace("{TAXONOMY}", json.dumps(genres, ensure_ascii=False))


def build_messages(batch: list, system_prompt: str) -> list:
    user = {"tags": batch}
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_corrective_messages(batch: list, system_prompt: str, raw_reply: str, invalid: list, problems: list) -> list:
    messages = build_messages(batch, system_prompt)
    messages.append({"role": "assistant", "content": raw_reply})
    messages.append({
        "role": "user",
        "content": (
            "Your previous reply had invalid or missing entries:\n"
            + "\n".join(problems[:20])
            + "\nReturn a corrected strict JSON object with classifications ONLY for these tags:\n"
            + json.dumps({"tags": invalid}, ensure_ascii=False)
        ),
    })
    return messages


def parse_llm_json(content: str):
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def validate_entries(requested: list, parsed: object, genres: dict):
    if not isinstance(parsed, dict):
        return {}, list(requested), ["response is not a JSON object"]
    entries = parsed.get("classifications")
    if not isinstance(entries, list):
        return {}, list(requested), ["response missing classifications list"]
    by_tag = {}
    for e in entries:
        if isinstance(e, dict) and isinstance(e.get("tag"), str):
            by_tag[e["tag"]] = e
    accepted, invalid, problems = {}, [], []
    for tag in requested:
        e = by_tag.get(tag)
        if e is None:
            invalid.append(tag)
            problems.append(f"missing entry: {tag!r}")
            continue
        is_genre = e.get("is_genre_tag")
        genre = e.get("genre") or None
        style = e.get("style") or None
        if not isinstance(is_genre, bool):
            invalid.append(tag)
            problems.append(f"is_genre_tag not boolean: {tag!r}")
            continue
        if not is_genre:
            if genre is None and style is None:
                accepted[tag] = {"is_genre_tag": False, "genre": None, "style": None}
            else:
                invalid.append(tag)
                problems.append(f"non-genre tag must have null genre/style: {tag!r}")
            continue
        if genre not in genres:
            invalid.append(tag)
            problems.append(f"genre not in closed list: {tag!r} -> {genre!r}")
            continue
        if style is not None and style not in genres[genre]:
            invalid.append(tag)
            problems.append(f"style {style!r} not under genre {genre!r}: {tag!r}")
            continue
        accepted[tag] = {"is_genre_tag": True, "genre": genre, "style": style}
    return accepted, invalid, problems


class LLMClient:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.json_mode = True
        self._lock = threading.Lock()
        self._consecutive_failures = 0

    def chat(self, messages: list) -> str:
        with self._lock:
            if self._consecutive_failures >= CIRCUIT_THRESHOLD:
                raise CircuitOpen(f"circuit open after {self._consecutive_failures} consecutive failures")
        body = {"model": self.model, "messages": messages, "temperature": 0}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/petinhoss7/spotify-analytics",
            "X-Title": "spotify-analytics-tag-classifier",
        }
        last_err = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                resp = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 400 and "response_format" in body:
                    body.pop("response_format")
                    self.json_mode = False
                    continue
                if resp.status_code == 200:
                    with self._lock:
                        self._consecutive_failures = 0
                    return resp.json()["choices"][0]["message"]["content"]
                if resp.status_code in RETRYABLE_STATUS:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                else:
                    raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:300]}")
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_err = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._consecutive_failures += 1
                failures = self._consecutive_failures
            if failures >= CIRCUIT_THRESHOLD:
                raise CircuitOpen(f"circuit open after {failures} consecutive failures; last error: {last_err}")
            time.sleep(min(60.0, 0.5 * 2**attempt) + random.uniform(0, 1))
        raise RuntimeError(f"OpenRouter failed after {MAX_API_ATTEMPTS} attempts: {last_err}")


class Logger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()

    def __call__(self, msg: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {msg}\n")
        print(msg, flush=True)


def atomic_write_csv(path: Path, header: list, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Classify raw tags into the Discogs closed list.")
    p.add_argument("--dry-run", action="store_true", help="run L1-L3 and print stats; no API calls, no files written")
    p.add_argument("--limit", type=int, default=None, help="cap the number of tags sent to the LLM (smoke test)")
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--overrides", type=Path, default=OVERRIDES_PATH, help="human-curated overrides (applied first)")
    p.add_argument("--force", action="store_true", help="ignore the LLM cache and re-classify everything")
    p.add_argument("--no-db", action="store_true", help="do not union the DuckDB staging vocabulary")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    load_env()
    try:
        genres, exact_index, ambiguous = load_taxonomy()
        aliases = load_aliases(ALIASES_PATH, genres, exact_index, ambiguous)
        overrides = load_overrides(args.overrides, genres)
        vocab = load_extract_vocab()
        if not args.no_db:
            vocab |= load_db_vocab()
    except BuildError as exc:
        print(f"BUILD ERROR (fail-fast): {exc}", file=sys.stderr)
        return 1

    log = Logger(LOGS / f"run_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.log")
    containment_entries = build_containment_index(exact_index, genres)
    n_collisions = len(ambiguous)
    log(f"taxonomy: {len(genres)} genres, {len(exact_index)} unambiguous keys, {n_collisions} ambiguous keys -> L4")
    log(f"overrides: {len(overrides)} curated entries from {args.overrides.name}")
    log(f"vocabulary: {len(vocab)} unique tags")

    results: dict[str, dict] = {}
    review: list[tuple[str, str]] = []
    pending: list[str] = []
    method_counts = {"manual": 0, "exact": 0, "alias": 0, "fuzzy": 0, "llm": 0, "noise": 0}
    interrupted = False

    for tag in sorted(vocab):
        try:
            q = normalize(tag)
            override = overrides.get(q)
            if override is not None:
                results[tag] = {
                    "is_genre_tag": override["is_genre_tag"],
                    "genre": override["genre"],
                    "style": override["style"],
                    "method": "manual",
                    "score": None,
                    "confidence": override["confidence"],
                }
                method_counts["manual"] += 1
                continue
            if not q:
                # non-Latin tag (CJK, Arabic, emoji...): normalize() cannot
                # reduce it, L4 judges it directly from the raw value
                pending.append(tag)
                continue
            if is_noise(q):
                results[tag] = {"is_genre_tag": False, "genre": None, "style": None,
                                "method": "noise", "score": None, "confidence": None}
                method_counts["noise"] += 1
                continue
            hit = static_classify(q, exact_index, aliases, containment_entries, ambiguous)
            if hit is None:
                pending.append(tag)
                continue
            pair, method, score = hit
            results[tag] = {
                "is_genre_tag": True,
                "genre": pair[0],
                "style": pair[1],
                "method": method,
                "score": score,
                "confidence": DEFAULT_SPECIFICITY,
            }
            method_counts[method] += 1
        except Exception as exc:
            review.append((tag, f"static_error: {type(exc).__name__}: {exc}"))

    log(f"L0 overrides: {method_counts['manual']}  L1 exact: {method_counts['exact']}  "
        f"L2 alias: {method_counts['alias']}  L3 containment: {method_counts['fuzzy']}  noise: {method_counts['noise']}")
    log(f"pending for L4: {len(pending)}  review so far: {len(review)}")

    if args.dry_run:
        print("\nDRY RUN - sample of pending tags (first 40):")
        for t in pending[:40]:
            print(f"  {t}")
        return 0

    cache = {} if args.force else load_cache(args.cache)
    to_classify = [t for t in pending if t not in cache]
    if args.limit is not None:
        to_classify = to_classify[: args.limit]
    log(f"L4: {len(to_classify)} tags to classify ({len(cache)} cached)")

    if to_classify:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        model = os.environ.get("L4_MODEL", "z-ai/glm-5.3-flash")
        if not api_key:
            log("ERROR: OPENROUTER_API_KEY missing from environment/.env - L4 skipped, partial map written")
            write_outputs(results, review)
            return 2
        client = LLMClient(api_key, model)
        system_prompt = build_system_prompt(genres)
        batches = [to_classify[i : i + args.batch_size] for i in range(0, len(to_classify), args.batch_size)]
        log(f"L4: {len(batches)} batches of <= {args.batch_size} tags, {args.workers} workers, model={model}")
        cache_lock = threading.Lock()
        interrupted = False
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futures = {ex.submit(classify_batch, client, b, system_prompt, genres): b for b in batches}
                for done, fut in enumerate(as_completed(futures), start=1):
                    batch = futures[fut]
                    try:
                        accepted, invalid, batch_review = fut.result()
                    except CircuitOpen as exc:
                        log(f"CIRCUIT OPEN: {exc}")
                        log("clean abort - cache is up to date, re-run the same command to resume")
                        for f in futures:
                            f.cancel()
                        write_outputs(results, review)
                        return 2
                    except Exception as exc:
                        batch_review = [(t, f"batch_error: {type(exc).__name__}: {exc}") for t in batch]
                        accepted, invalid = {}, []
                    with cache_lock:
                        results.update({
                            t: {**v, "method": "llm", "score": None, "confidence": DEFAULT_SPECIFICITY}
                            for t, v in accepted.items()
                        })
                        review.extend(batch_review)
                        cache.update(accepted)
                        save_cache(args.cache, cache)
                    log(f"batch {done}/{len(batches)}  classified={len(accepted)}  review={len(batch_review) + len(invalid)}")
        except KeyboardInterrupt:
            interrupted = True
            log("interrupted - cache flushed, partial map written; re-run to resume")

    for t in pending:
        cached = cache.get(t)
        if cached and t not in results:
            results[t] = {
                "is_genre_tag": cached["is_genre_tag"],
                "genre": cached["genre"],
                "style": cached["style"],
                "method": "llm",
                "score": None,
                "confidence": DEFAULT_SPECIFICITY,
            }
    method_counts["llm"] = sum(1 for v in results.values() if v["method"] == "llm")
    if method_counts["llm"] or cache:
        log(f"L4: {method_counts['llm']} classified by LLM (cache: {len(cache)} entries)")

    write_outputs(results, review)
    total = sum(method_counts.values())
    log(f"DONE: {total} classified, {len(review)} review items -> {LOGS / 'review_pending.csv'}")
    for m, c in method_counts.items():
        log(f"  {m}: {c}")
    if interrupted:
        return 130
    return 0


def classify_batch(client: LLMClient, batch: list, system_prompt: str, genres: dict):
    messages = build_messages(batch, system_prompt)
    content = client.chat(messages)
    parsed = parse_llm_json(content)
    accepted, invalid, problems = validate_entries(batch, parsed, genres)
    batch_review: list[tuple[str, str]] = []
    if invalid:
        cmsgs = build_corrective_messages(batch, system_prompt, content, invalid, problems)
        try:
            content2 = client.chat(cmsgs)
            parsed2 = parse_llm_json(content2)
            acc2, invalid, problems2 = validate_entries(invalid, parsed2, genres)
            accepted.update(acc2)
            for t in invalid:
                batch_review.append((t, "llm_invalid: " + (problems2[0] if problems2 else "unresolved")))
        except CircuitOpen:
            raise
        except Exception as exc:
            for t in invalid:
                batch_review.append((t, f"corrective_retry_failed: {type(exc).__name__}"))
    return accepted, invalid, batch_review


def write_outputs(results: dict, review: list) -> None:
    rows = []
    for tag in sorted(results):
        r = results[tag]
        confidence = r.get("confidence")
        rows.append([
            tag,
            "true" if r["is_genre_tag"] else "false",
            r["genre"] or "",
            r["style"] or "",
            r["method"],
            r["score"] if r["score"] is not None else "",
            f"{confidence:.4f}".rstrip("0").rstrip(".") if confidence is not None else "",
        ])
    atomic_write_csv(
        SEEDS / "tag_genre_map.csv",
        ["raw_tag", "is_genre_tag", "discogs_genre", "discogs_style", "match_method", "match_score", "confidence"],
        rows,
    )
    atomic_write_csv(LOGS / "review_pending.csv", ["raw_tag", "reason"], sorted(review))
    print(f"wrote {SEEDS / 'tag_genre_map.csv'} ({len(rows)} rows)")


if __name__ == "__main__":
    sys.exit(main())
