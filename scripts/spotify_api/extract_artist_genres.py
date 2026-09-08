import os
import time
import requests
import duckdb
from dotenv import load_dotenv
from datetime import datetime


# =============================
# Configuration
# =============================

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

DB_PATH = "data/spotify.duckdb"

SLEEP_BETWEEN_REQUESTS = 0.1


# =============================
# Spotify Authentication
# =============================

def get_access_token():

    url = "https://accounts.spotify.com/api/token"

    response = requests.post(
        url,
        data={
            "grant_type": "client_credentials"
        },
        auth=(
            CLIENT_ID,
            CLIENT_SECRET
        )
    )

    response.raise_for_status()

    return response.json()["access_token"]


# =============================
# Get artists without genres
# =============================

def get_artists_without_genres(conn):

    query = """
    SELECT artist_id
    FROM raw.raw_spotify_artists
    WHERE artist_id IS NOT NULL
      AND TRIM(artist_id) <> ''
      AND (
            genres IS NULL
            OR genres = ''
            OR genres = '[]'
          )
    """

    return [
        row[0]
        for row in conn.execute(query).fetchall()
    ]


# =============================
# Spotify API
# GET /v1/artists/{id}
# =============================

def get_artist_from_spotify(artist_id, token):

    url = (
        f"https://api.spotify.com/v1/artists/{artist_id}"
    )

    headers = {
        "Authorization": f"Bearer {token}"
    }


    while True:

        response = requests.get(
            url,
            headers=headers
        )


        # Rate limit
        if response.status_code == 429:

            retry = int(
                response.headers.get(
                    "Retry-After",
                    10
                )
            )

            print(
                f"Rate limit. Waiting {retry}s"
            )

            time.sleep(retry)

            continue


        # Artist not found / forbidden
        if response.status_code != 200:

            print(
                f"Failed {artist_id}: "
                f"{response.status_code}"
            )

            print(response.text)

            return None


        return response.json()


# =============================
# Insert result
# =============================

def insert_artist_genre(conn, artist):

    conn.execute(
        """
        INSERT OR REPLACE INTO raw.raw_spotify_artist_genres
        (
            artist_id,
            genres,
            extracted_at
        )
        VALUES (?, ?, ?)
        """,
        [
            artist["id"],
            artist.get("genres", []),
            datetime.now()
        ]
    )


# =============================
# Main
# =============================

def main():

    conn = duckdb.connect(DB_PATH)


    artists = get_artists_without_genres(conn)


    print(
        f"{len(artists)} artists without genres found"
    )


    token = get_access_token()


    success = 0
    failed = 0


    for index, artist_id in enumerate(artists):

        print(
            f"Processing {index+1}/{len(artists)} : {artist_id}"
        )


        artist = get_artist_from_spotify(
            artist_id,
            token
        )


        if artist:

            insert_artist_genre(
                conn,
                artist
            )

            conn.commit()

            success += 1

        else:

            failed += 1


        time.sleep(
            SLEEP_BETWEEN_REQUESTS
        )


    conn.close()


    print("-----------------------")
    print(
        f"Completed"
    )
    print(
        f"Success : {success}"
    )
    print(
        f"Failed  : {failed}"
    )


if __name__ == "__main__":
    main()