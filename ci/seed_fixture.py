"""Build a small, deterministic DuckDB database for CI.

The real project reads Parquet exports that are not versioned (see
.gitignore), so CI cannot use production data. This script recreates the
six ``raw`` source tables with a handful of internally consistent rows
that exercise every branch of the DAG:

* 5 artists: a 2-source/2-genre artist with styles (Alpha), a
  style-only artist (Beta), an artist with no genre evidence (Gamma,
  feeding the ``unclassified`` bucket), a single-source artist (Delta),
  and a second collaborator (Epsilon, plus a ``non_genre`` and a
  ``noise`` tag);
* 8 tracks: solo, collaboration, podcast, audiobook, a track missing
  from the track/artist bridge (``no_artist_data`` bucket) and a
  sub-30s listen;
* streams spread over two months, including one play duplicated across
  two export files (deduplication guard).

Usage::

    python ci/seed_fixture.py
    dbt build --profiles-dir ci --target ci

The database path defaults to ``ci/fixture.duckdb`` and can be
overridden with the ``CI_DUCKDB_PATH`` environment variable.
"""

from __future__ import annotations

import json
import os
import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB_PATH = pathlib.Path(os.environ.get("CI_DUCKDB_PATH", ROOT / "ci" / "fixture.duckdb"))

LOADED_AT = "2024-03-01 00:00:00"
EXTRACTED_AT = "2024-03-01 00:00:00"

DDL = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE OR REPLACE TABLE raw.RAW_SPOTIFY_STREAMING (
    raw_record VARCHAR,
    file_name VARCHAR,
    load_timestamp TIMESTAMP
);

CREATE OR REPLACE TABLE raw.RAW_SPOTIFY_AUDIO_FEATURES (
    track_uri VARCHAR,
    raw_audio_features VARCHAR,
    loaded_at TIMESTAMP
);

CREATE OR REPLACE TABLE raw.RAW_SPOTIFY_ARTISTS (
    artist_id VARCHAR,
    artist_name VARCHAR,
    popularity INTEGER,
    followers_total INTEGER,
    genres VARCHAR,
    artist_uri VARCHAR,
    loaded_at TIMESTAMP
);

CREATE OR REPLACE TABLE raw.RAW_SPOTIFY_TRACK_ARTISTS (
    track_id VARCHAR,
    artist_id VARCHAR,
    artist_name VARCHAR,
    loaded_at TIMESTAMP
);

CREATE OR REPLACE TABLE raw.RAW_LASTFM_ARTIST_GENRES (
    artist_id VARCHAR,
    spotify_artist_name VARCHAR,
    lastfm_artist_name VARCHAR,
    lastfm_tags JSON,
    found BOOLEAN,
    extracted_at TIMESTAMP
);

CREATE OR REPLACE TABLE raw.RAW_MUSICBRAINZ_ARTISTS (
    artist_id VARCHAR,
    spotify_artist_name VARCHAR,
    search_name VARCHAR,
    found BOOLEAN,
    score INTEGER,
    mbid VARCHAR,
    musicbrainz_name VARCHAR,
    sort_name VARCHAR,
    disambiguation VARCHAR,
    artist_type VARCHAR,
    artist_type_id VARCHAR,
    gender VARCHAR,
    country VARCHAR,
    area VARCHAR,
    begin_date DATE,
    end_date DATE,
    ended BOOLEAN,
    genres JSON,
    tags JSON,
    aliases JSON,
    error_message VARCHAR,
    extracted_at TIMESTAMP
);
"""

# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------

ARTISTS = [
    # artist_id, name, popularity, followers, spotify genres
    ("artist001", "Alpha", 80, 1_000_000, ["alternative rock", "indie pop"]),
    ("artist002", "Beta", 70, 500_000, ["synth-pop", "electronic"]),
    ("artist003", "Gamma", 50, 100_000, []),
    ("artist004", "Delta", 40, 50_000, ["jazz"]),
    ("artist005", "Epsilon", 60, 200_000, ["hip hop"]),
]

LASTFM = [
    # artist_id, name, lastfm name, tags, found
    ("artist001", "Alpha", "Alpha", [{"name": "alternative rock", "count": 200}, {"name": "indie pop", "count": 100}], True),
    ("artist002", "Beta", "Beta", [{"name": "synth-pop", "count": 50}, {"name": "", "count": 0}], True),
    ("artist003", "Gamma", None, [], False),
    ("artist004", "Delta", "Delta", [{"name": "french", "count": 5}], True),
    ("artist005", "Epsilon", "Epsilon", [{"name": "hip hop", "count": 10}, {"name": "80s", "count": 3}], True),
]

MUSICBRAINZ = [
    # artist_id, name, found, tags
    ("artist001", "Alpha", True, [{"name": "alternative rock", "count": 100}, {"name": "indie pop", "count": 50}]),
    ("artist002", "Beta", True, [{"name": "electronic", "count": 30}]),
    ("artist003", "Gamma", False, []),
    ("artist004", "Delta", False, []),
    ("artist005", "Epsilon", True, [{"name": "hip hop", "count": 20}]),
]

# ---------------------------------------------------------------------------
# Tracks and audio features
# ---------------------------------------------------------------------------

TRACKS = {
    "track001": {"name": "Alpha Song", "album": "Alpha Album", "artists": ["artist001"]},
    "track002": {"name": "Alpha & Epsilon", "album": "Collab Album", "artists": ["artist001", "artist005"]},
    "track003": {"name": "Beta Song", "album": "Beta Album", "artists": ["artist002"]},
    "track004": {"name": "Gamma Song", "album": "Gamma Album", "artists": ["artist003"]},
    "track005": {"name": "Delta Song", "album": "Delta Album", "artists": ["artist004"]},
    "track006": {"name": "Unmapped Song", "album": "Unknown Album", "artists": []},
}

AUDIO_FEATURES = {
    "track001": {"danceability": 0.61, "energy": 0.82, "valence": 0.44, "tempo": 124.0},
    "track002": {"danceability": 0.72, "energy": 0.66, "valence": 0.71, "tempo": 96.0},
    "track003": {"danceability": 0.55, "energy": 0.93, "valence": 0.28, "tempo": 138.0},
    "track004": {"danceability": 0.48, "energy": 0.35, "valence": 0.22, "tempo": 82.0},
    "track005": {"danceability": 0.64, "energy": 0.29, "valence": 0.58, "tempo": 110.0},
    "track006": {"danceability": 0.70, "energy": 0.50, "valence": 0.50, "tempo": 100.0},
}


def audio_features(track_id: str, overrides: dict | None = None) -> str:
    payload = {
        "acousticness": 0.10,
        "analysis_url": f"https://api.spotify.com/v1/audio-analysis/{track_id}",
        "danceability": 0.60,
        "duration_ms": 240_000,
        "energy": 0.80,
        "id": track_id,
        "instrumentalness": 0.0,
        "key": 5,
        "liveness": 0.10,
        "loudness": -6.0,
        "mode": 1,
        "speechiness": 0.05,
        "tempo": 120.0,
        "time_signature": 4,
        "track_href": f"https://api.spotify.com/v1/tracks/{track_id}",
        "type": "audio_features",
        "uri": f"spotify:track:{track_id}",
        "valence": 0.60,
    }
    payload.update(overrides or {})
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------

FILE_00 = "Streaming_History_Audio_2024_0.json"
FILE_01 = "Streaming_History_Audio_2024_1.json"


def stream(
    uri: str | None,
    ts: str,
    ms_played: int,
    file_name: str,
    loaded_at: str,
    artist: str | None,
    track: str | None,
    album: str | None,
    **overrides,
) -> tuple[str, str, str]:
    record = {
        "ts": ts,
        "ms_played": ms_played,
        "platform": "Windows 10 (10.0.19045; x86_64)",
        "conn_country": "FR",
        "ip_addr": "203.0.113.10",
        "master_metadata_track_name": track,
        "master_metadata_album_artist_name": artist,
        "master_metadata_album_album_name": album,
        "spotify_track_uri": uri,
        "episode_name": None,
        "episode_show_name": None,
        "spotify_episode_uri": None,
        "audiobook_title": None,
        "audiobook_chapter_title": None,
        "audiobook_uri": None,
        "audiobook_chapter_uri": None,
        "reason_start": "trackdone",
        "reason_end": "trackdone",
        "shuffle": False,
        "skipped": False,
        "offline": False,
        "offline_timestamp": None,
        "incognito_mode": False,
    }
    record.update(overrides)
    return (json.dumps(record, ensure_ascii=False), file_name, loaded_at)


STREAMS = [
    # January 2024 - Alpha solo + one collaboration
    stream("spotify:track:track001", "2024-01-10T20:00:00Z", 180_000, FILE_00, LOADED_AT,
           "Alpha", "Alpha Song", "Alpha Album"),
    stream("spotify:track:track001", "2024-01-15T21:10:00Z", 200_000, FILE_00, LOADED_AT,
           "Alpha", "Alpha Song", "Alpha Album"),
    stream("spotify:track:track002", "2024-01-20T22:00:00Z", 150_000, FILE_00, LOADED_AT,
           "Alpha, Epsilon", "Alpha & Epsilon", "Collab Album"),
    # Duplicate of the first play, re-exported in a later file (dedup guard)
    stream("spotify:track:track001", "2024-01-10T20:00:00Z", 180_000, FILE_01, "2024-03-02 00:00:00",
           "Alpha", "Alpha Song", "Alpha Album"),
    # February 2024 - one artist per reconciliation bucket
    stream("spotify:track:track003", "2024-02-02T10:00:00Z", 60_000, FILE_01, LOADED_AT,
           "Beta", "Beta Song", "Beta Album"),
    stream("spotify:track:track004", "2024-02-03T11:00:00Z", 120_000, FILE_01, LOADED_AT,
           "Gamma", "Gamma Song", "Gamma Album"),
    stream("spotify:track:track005", "2024-02-04T12:00:00Z", 90_000, FILE_01, LOADED_AT,
           "Delta", "Delta Song", "Delta Album"),
    stream("spotify:track:track006", "2024-02-05T13:00:00Z", 45_000, FILE_01, LOADED_AT,
           "Unknown Artist", "Unmapped Song", "Unknown Album"),
    # Excluded upstream: podcast and audiobook
    stream(None, "2024-02-06T14:00:00Z", 300_000, FILE_01, LOADED_AT,
           None, None, None,
           episode_name="Episode 1", episode_show_name="A Podcast",
           spotify_episode_uri="spotify:episode:episode001"),
    stream(None, "2024-02-07T15:00:00Z", 120_000, FILE_01, LOADED_AT,
           None, None, None,
           audiobook_title="A Book", audiobook_chapter_title="Chapter 1",
           audiobook_uri="spotify:show:book001", audiobook_chapter_uri="spotify:chapter:chapter001"),
    # Sub-30s listen (is_meaningful_listen = false)
    stream("spotify:track:track003", "2024-02-08T16:00:00Z", 12_000, FILE_01, LOADED_AT,
           "Beta", "Beta Song", "Beta Album"),
]


def build() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in (".wal", ".tmp"):
        pathlib.Path(f"{DB_PATH}{suffix}").unlink(missing_ok=True)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    con.execute(DDL)

    con.executemany(
        "INSERT INTO raw.RAW_SPOTIFY_ARTISTS VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (artist_id, name, popularity, followers, json.dumps(genres),
             f"spotify:artist:{artist_id}", LOADED_AT)
            for artist_id, name, popularity, followers, genres in ARTISTS
        ],
    )

    con.executemany(
        "INSERT INTO raw.RAW_LASTFM_ARTIST_GENRES VALUES (?, ?, ?, CAST(? AS JSON), ?, ?)",
        [
            (artist_id, name, lastfm_name, json.dumps(tags), found, EXTRACTED_AT)
            for artist_id, name, lastfm_name, tags, found in LASTFM
        ],
    )

    con.executemany(
        "INSERT INTO raw.RAW_MUSICBRAINZ_ARTISTS ("
        "artist_id, spotify_artist_name, search_name, found, score, mbid, "
        "musicbrainz_name, sort_name, disambiguation, artist_type, artist_type_id, "
        "gender, country, area, begin_date, end_date, ended, genres, tags, aliases, "
        "error_message, extracted_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON), CAST(? AS JSON), CAST(? AS JSON), ?, ?)",
        [
            (
                artist_id, name, name.lower(), found, 100 if found else None,
                f"mbid-{artist_id}" if found else None,
                name if found else None, name if found else None, "", "Group", None,
                None, "FR" if found else None, "France" if found else None,
                None, None, False, json.dumps([]), json.dumps(tags), json.dumps([]),
                None, EXTRACTED_AT,
            )
            for artist_id, name, found, tags in MUSICBRAINZ
        ],
    )

    names = {artist_id: name for artist_id, name, _, _, _ in ARTISTS}
    con.executemany(
        "INSERT INTO raw.RAW_SPOTIFY_TRACK_ARTISTS VALUES (?, ?, ?, ?)",
        [
            (track_id, artist_id, names[artist_id], LOADED_AT)
            for track_id, meta in TRACKS.items()
            for artist_id in meta["artists"]
        ],
    )

    con.executemany(
        "INSERT INTO raw.RAW_SPOTIFY_AUDIO_FEATURES VALUES (?, ?, ?)",
        [
            (f"spotify:track:{track_id}", audio_features(track_id, overrides), LOADED_AT)
            for track_id, overrides in AUDIO_FEATURES.items()
        ],
    )

    con.executemany(
        "INSERT INTO raw.RAW_SPOTIFY_STREAMING VALUES (?, ?, ?)",
        STREAMS,
    )

    counts = {
        table: con.execute(f"SELECT count(*) FROM raw.{table}").fetchone()[0]
        for table in (
            "RAW_SPOTIFY_STREAMING",
            "RAW_SPOTIFY_AUDIO_FEATURES",
            "RAW_SPOTIFY_ARTISTS",
            "RAW_SPOTIFY_TRACK_ARTISTS",
            "RAW_LASTFM_ARTIST_GENRES",
            "RAW_MUSICBRAINZ_ARTISTS",
        )
    }
    con.close()

    print(f"Fixture database written to {DB_PATH}")
    for table, count in counts.items():
        print(f"  raw.{table}: {count} rows")


if __name__ == "__main__":
    build()