import os
import time
import json
import unicodedata
import requests
import duckdb

from datetime import datetime
from dotenv import load_dotenv


# =========================
# CONFIG
# =========================

load_dotenv()

DB_PATH = os.getenv(
    "DUCKDB_PATH",
    "data/spotify.duckdb"
)

MB_USER_AGENT = os.getenv(
    "MUSICBRAINZ_USER_AGENT"
)

BASE_URL = "https://musicbrainz.org/ws/2"

MIN_SCORE = 90
SLEEP_TIME = 1.1


# =========================
# HELPERS
# =========================
def normalize_date(value):

    if not value:
        return None

    # YYYY
    if len(value) == 4:
        return f"{value}-01-01"

    # YYYY-MM
    if len(value) == 7:
        return f"{value}-01"

    # YYYY-MM-DD
    return value

def normalize_name(name):

    if not name:
        return ""

    name = unicodedata.normalize(
        "NFKD",
        name
    )

    name = "".join(
        c for c in name
        if not unicodedata.combining(c)
    )

    name = (
        name.lower()
        .replace("&", "and")
        .replace(".", "")
        .replace(",", "")
        .replace("'", "")
    )

    return " ".join(name.split())


def api_get(url, params):

    headers = {
        "User-Agent": MB_USER_AGENT
    }

    for attempt in range(3):

        try:

            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=20
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in [429, 503]:
                print(
                    f"Rate limit/server busy ({response.status_code})"
                )
                time.sleep(5)

            else:
                print(
                    f"HTTP {response.status_code}"
                )
                return None


        except Exception as e:

            print(
                f"Request error: {e}"
            )

            time.sleep(5)


    return None



# =========================
# MUSICBRAINZ SEARCH
# =========================

def search_artist(name):

    data = api_get(
        f"{BASE_URL}/artist",
        {
            "query": f'artist:"{name}"',
            "fmt": "json",
            "limit": 1
        }
    )

    time.sleep(SLEEP_TIME)

    if not data:
        return None

    artists = data.get(
        "artists",
        []
    )

    if not artists:
        return None

    return artists[0]



# =========================
# DETAILS
# =========================

def get_artist_details(mbid):

    data = api_get(
        f"{BASE_URL}/artist/{mbid}",
        {
            "fmt": "json",
            "inc": "genres+tags+aliases"
        }
    )

    time.sleep(SLEEP_TIME)

    return data



# =========================
# INSERT
# =========================

def insert_artist(conn, row):

    conn.execute(
        """
        INSERT OR REPLACE INTO raw.RAW_MUSICBRAINZ_ARTISTS (

            ARTIST_ID,
            SPOTIFY_ARTIST_NAME,
            SEARCH_NAME,

            FOUND,
            SCORE,

            MBID,
            MUSICBRAINZ_NAME,
            SORT_NAME,
            DISAMBIGUATION,

            ARTIST_TYPE,
            ARTIST_TYPE_ID,
            GENDER,

            COUNTRY,
            AREA,

            BEGIN_DATE,
            END_DATE,
            ENDED,

            GENRES,
            TAGS,
            ALIASES,

            ERROR_MESSAGE,

            EXTRACTED_AT

        )

        VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        """,
        row
    )



# =========================
# MAIN
# =========================

def main():

    conn = duckdb.connect(DB_PATH)

    print(
        f"Database: {DB_PATH}"
    )


    artists = conn.execute(
        """
        SELECT
            s.ARTIST_ID,
            s.ARTIST_NAME

        FROM raw.RAW_SPOTIFY_ARTISTS s

        LEFT JOIN raw.RAW_MUSICBRAINZ_ARTISTS m

        ON s.ARTIST_ID = m.ARTIST_ID

        WHERE m.ARTIST_ID IS NULL

        """
    ).fetchall()


    total = len(artists)

    print(
        f"{total} artists to process"
    )


    found = 0
    rejected = 0
    errors = 0


    for i, (artist_id, artist_name) in enumerate(
        artists,
        start=1
    ):
        print(f"Processing {i}/{total}: {artist_name}")
        search_name = normalize_name(
            artist_name
        )


        try:

            result = search_artist(
                search_name
            )


            # Aucun résultat
            if not result:

                insert_artist(
                    conn,
                    (
                        artist_id,
                        artist_name,
                        search_name,

                        False,
                        None,

                        None,
                        None,
                        None,
                        None,

                        None,
                        None,
                        None,

                        None,
                        None,

                        None,
                        None,
                        None,

                        json.dumps([]),
                        json.dumps([]),
                        json.dumps([]),

                        "No MusicBrainz result",

                        datetime.now()
                    )
                )

                rejected += 1
                continue



            score = int(
                result.get(
                    "score",
                    0
                )
            )


            # Score insuffisant

            if score < MIN_SCORE:

                insert_artist(
                    conn,
                    (
                        artist_id,
                        artist_name,
                        search_name,

                        False,
                        score,

                        None,
                        result.get("name"),
                        result.get("sort-name"),
                        result.get("disambiguation"),

                        None,
                        None,
                        None,

                        None,
                        None,

                        None,
                        None,
                        None,

                        json.dumps([]),
                        json.dumps([]),
                        json.dumps([]),

                        "Score below threshold",

                        datetime.now()
                    )
                )

                rejected += 1
                continue



            # DETAIL

            mbid = result["id"]

            details = get_artist_details(
                mbid
            )


            if not details:

                errors += 1
                continue


            life = details.get(
                "life-span",
                {}
            )


            genres = [
                g["name"]
                for g in details.get(
                    "genres",
                    []
                )
            ]


            tags = [
                t["name"]
                for t in details.get(
                    "tags",
                    []
                )
            ]


            aliases = details.get(
                "aliases",
                []
            )


            insert_artist(
                conn,
                (
                    artist_id,
                    artist_name,
                    search_name,

                    True,
                    score,

                    mbid,
                    details.get("name"),
                    details.get("sort-name"),
                    details.get("disambiguation"),

                    details.get("type"),
                    details.get("type-id"),
                    details.get("gender"),

                    details.get("country"),
                    json.dumps(
                        details.get("area")
                    ),

                    normalize_date(life.get("begin")),
                    normalize_date(life.get("end")),
                    life.get("ended"),

                    json.dumps(genres),
                    json.dumps(tags),
                    json.dumps(aliases),

                    None,

                    datetime.now()
                )
            )


            found += 1



        except Exception as e:

            errors += 1

            print(
                f"ERROR {artist_name}: {e}"
            )


        if i % 50 == 0:

            conn.commit()

            print(
                f"{i}/{total} | "
                f"found={found} | "
                f"rejected={rejected} | "
                f"errors={errors}"
            )


    conn.commit()

    print(
        "DONE"
    )


if __name__ == "__main__":
    main()