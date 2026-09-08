import os
import json
import time
import asyncio
import aiohttp
import duckdb

from dotenv import load_dotenv
from datetime import datetime


# =========================
# CONFIG
# =========================

load_dotenv()

LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")

DB_PATH = r"C:\Users\Peter Bardawil\projects\Spotify-Analytics\data\spotify.duckdb"

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"

MAX_WORKERS = 3

BATCH_SIZE = 100

REQUEST_DELAY = 0.25


# =========================
# READ ARTISTS
# =========================

def get_artists(conn):

    query = """

    SELECT
        a.ARTIST_ID,
        a.ARTIST_NAME

    FROM raw.RAW_SPOTIFY_ARTISTS a

    LEFT JOIN raw.RAW_LASTFM_ARTIST_GENRES l
        ON a.ARTIST_ID = l.ARTIST_ID

    WHERE a.ARTIST_ID IS NOT NULL
      AND a.ARTIST_NAME IS NOT NULL
      AND l.ARTIST_ID IS NULL

    """

    return conn.execute(query).fetchall()



# =========================
# LAST FM REQUEST
# =========================

async def fetch_lastfm(
        session,
        artist_id,
        artist_name,
        semaphore
):

    async with semaphore:

        params = {

            "method": "artist.getTopTags",

            "artist": artist_name,

            "api_key": LASTFM_API_KEY,

            "format": "json"

        }


        try:

            async with session.get(
                LASTFM_URL,
                params=params,
                timeout=15
            ) as response:


                data = await response.json()


                # Rate limiting protection

                await asyncio.sleep(
                    REQUEST_DELAY
                )


                # API error

                if (
                    "error" in data
                    or "toptags" not in data
                ):

                    return {

                        "artist_id": artist_id,

                        "spotify_artist_name": artist_name,

                        "lastfm_artist_name": None,

                        "tags": [],

                        "found": False
                    }



                top_tags = data.get(
                    "toptags",
                    {}
                )


                tags = top_tags.get(
                    "tag",
                    []
                )


                # Last.fm returns dict if only one tag

                if isinstance(tags, dict):

                    tags = [tags]


                cleaned_tags = []


                for tag in tags:


                    if isinstance(tag, dict):

                        cleaned_tags.append(

                            {

                                "name": tag.get(
                                    "name"
                                ),

                                "count": int(
                                    tag.get(
                                        "count",
                                        0
                                    )
                                )

                            }

                        )



                lastfm_name = (
                    top_tags
                    .get("@attr", {})
                    .get(
                        "artist",
                        artist_name
                    )
                )



                return {


                    "artist_id": artist_id,


                    "spotify_artist_name": artist_name,


                    "lastfm_artist_name": lastfm_name,


                    "tags": cleaned_tags,


                    "found": True


                }



        except Exception as e:


            print(
                f"\nERROR {artist_name}: {e}"
            )


            return {


                "artist_id": artist_id,


                "spotify_artist_name": artist_name,


                "lastfm_artist_name": None,


                "tags": [],


                "found": False


            }




# =========================
# INSERT BATCH
# =========================

def insert_batch(conn, rows):


    values = []


    for r in rows:


        values.append(

            (

                r["artist_id"],

                r["spotify_artist_name"],

                r["lastfm_artist_name"],

                json.dumps(
                    r["tags"],
                    ensure_ascii=False
                ),

                r["found"],

                datetime.now()

            )

        )



    conn.executemany(

        """

        INSERT OR REPLACE INTO raw.RAW_LASTFM_ARTIST_GENRES

        (

            ARTIST_ID,

            SPOTIFY_ARTIST_NAME,

            LASTFM_ARTIST_NAME,

            LASTFM_TAGS,

            FOUND,

            EXTRACTED_AT

        )

        VALUES (?, ?, ?, ?, ?, ?)

        """,

        values

    )


    conn.commit()




# =========================
# MAIN
# =========================

async def main():


    conn = duckdb.connect(
        DB_PATH
    )


    artists = get_artists(
        conn
    )


    total = len(
        artists
    )


    print(
        f"{total} artists to process"
    )


    semaphore = asyncio.Semaphore(
        MAX_WORKERS
    )


    connector = aiohttp.TCPConnector(
        limit=MAX_WORKERS
    )


    processed = 0

    found = 0

    missing = 0


    batch = []


    start = time.time()



    async with aiohttp.ClientSession(
        connector=connector
    ) as session:



        tasks = []


        for artist_id, artist_name in artists:


            tasks.append(

                fetch_lastfm(

                    session,

                    artist_id,

                    artist_name,

                    semaphore

                )

            )



        for task in asyncio.as_completed(tasks):


            result = await task


            batch.append(
                result
            )


            processed += 1


            if result["found"]:

                found += 1

            else:

                missing += 1



            if len(batch) >= BATCH_SIZE:


                insert_batch(

                    conn,

                    batch

                )


                batch = []



            elapsed = (
                time.time()
                -
                start
            )


            speed = (
                processed /
                elapsed
            )


            print(

                f"{processed}/{total} "
                f"| found={found} "
                f"| missing={missing} "
                f"| {speed:.2f}/sec",

                end="\r"

            )



    if batch:

        insert_batch(
            conn,
            batch
        )


    conn.close()


    print("\nDONE")



if __name__ == "__main__":

    asyncio.run(main())