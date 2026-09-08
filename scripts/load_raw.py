import duckdb
import os

DB_PATH = "data/spotify.duckdb"
PARQUET_PATH = "D:/snow"

conn = duckdb.connect(DB_PATH)

# Création du schéma RAW
conn.execute("""
CREATE SCHEMA IF NOT EXISTS RAW;
""")

tables = {
    "RAW_SPOTIFY_ARTISTS": "RAW_SPOTIFY_ARTISTS",
    "RAW_SPOTIFY_AUDIO_FEATURES": "RAW_SPOTIFY_AUDIO_FEATURES",
    "RAW_SPOTIFY_STREAMING": "RAW_SPOTIFY_STREAMING",
    "RAW_SPOTIFY_TRACK_ARTISTS": "RAW_SPOTIFY_TRACK_ARTISTS",
    "RAW_SPOTIFY_TRACK_LOOKUP": "RAW_SPOTIFY_TRACK_LOOKUP",
}

for table, folder in tables.items():

    parquet_file = f"{PARQUET_PATH}/{folder}/*.parquet"

    print(f"Loading {table}...")

    conn.execute(f"""
        CREATE OR REPLACE TABLE RAW.{table} AS
        SELECT *
        FROM read_parquet('{parquet_file}');
    """)

    count = conn.execute(
        f"SELECT COUNT(*) FROM RAW.{table}"
    ).fetchone()[0]

    print(f"{table}: {count} rows")

conn.close()

print("RAW migration completed.")