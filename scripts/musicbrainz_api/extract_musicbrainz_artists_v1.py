import os
import json
import time
import unicodedata
import requests
import duckdb

from datetime import datetime,timedelta
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

# MusicBrainz rate limit
SLEEP_TIME = 1.05



# =========================
# HELPERS
# =========================

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



def normalize_date(value):

    if not value:
        return None

    # YYYY
    if len(value) == 4:
        return f"{value}-01-01"

    # YYYY-MM
    if len(value) == 7:
        return f"{value}-01"

    return value



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


            elif response.status_code in [429, 503]:

                print(
                    f"MusicBrainz busy {response.status_code}, retry..."
                )

                time.sleep(5)


            else:

                print(
                    f"HTTP {response.status_code}: {response.text[:100]}"
                )

                return None



        except Exception as e:

            print(
                f"Request error: {e}"
            )

            time.sleep(5)



    return None




# =========================
# MUSICBRAINZ SEARCH ONLY
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


    conn = duckdb.connect(
        DB_PATH
    )


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
    start_time = time.time()


    for i, (artist_id, artist_name) in enumerate(
        artists,
        start=1
    ):


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

                        None,
                        None,
                        None,

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

                        result.get("id"),

                        result.get("name"),
                        result.get("sort-name"),
                        result.get("disambiguation"),


                        result.get("type"),
                        result.get("type-id"),
                        result.get("gender"),


                        result.get("country"),
                        json.dumps(
                            result.get("area")
                        ),


                        normalize_date(
                            result.get(
                                "life-span",
                                {}
                            ).get("begin")
                        ),

                        normalize_date(
                            result.get(
                                "life-span",
                                {}
                            ).get("end")
                        ),

                        result.get(
                            "life-span",
                            {}
                        ).get("ended"),


                        None,
                        None,
                        None,


                        "Score below threshold",

                        datetime.now()

                    )
                )


                rejected += 1
                continue





            # MATCH OK

            insert_artist(
                conn,
                (

                    artist_id,
                    artist_name,
                    search_name,

                    True,
                    score,


                    result.get("id"),

                    result.get("name"),
                    result.get("sort-name"),
                    result.get("disambiguation"),


                    result.get("type"),
                    result.get("type-id"),
                    result.get("gender"),


                    result.get("country"),

                    json.dumps(
                        result.get("area")
                    ),


                    normalize_date(
                        result.get(
                            "life-span",
                            {}
                        ).get("begin")
                    ),

                    normalize_date(
                        result.get(
                            "life-span",
                            {}
                        ).get("end")
                    ),

                    result.get(
                        "life-span",
                        {}
                    ).get("ended"),


                    None,
                    None,
                    None,


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




        if i % 10 == 0:

            elapsed = time.time() - start_time

            speed = i / elapsed if elapsed > 0 else 0

            remaining = total - i

            eta_seconds = (
                remaining / speed
                if speed > 0
                else 0
            )

            eta = str(
                    timedelta(
                        seconds=int(eta_seconds)
                )
            )

            completion = (
                i / total * 100
                if total > 0
                else 0
            )


            print(
                f"{i}/{total} "
                f"({completion:.2f}%) | "
                f"found={found} | "
                f"rejected={rejected} | "
                f"errors={errors} | "
                f"speed={speed:.2f} artist/s | "
                f"ETA={eta}"
            )



        if i % 100 == 0:

            conn.commit()



    conn.commit()


    print(
        "DONE"
    )



if __name__ == "__main__":
    main()