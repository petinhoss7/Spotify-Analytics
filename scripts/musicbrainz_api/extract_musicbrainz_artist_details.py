import os
import json
import time
import requests
import duckdb
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

DB_PATH = os.getenv("DUCKDB_PATH","data/spotify.duckdb")
USER_AGENT = os.getenv("MUSICBRAINZ_USER_AGENT")
BASE="https://musicbrainz.org/ws/2"
SLEEP=1.05

def api_get(mbid):
    headers={"User-Agent":USER_AGENT}
    url=f"{BASE}/artist/{mbid}"
    params={"fmt":"json","inc":"genres+tags+aliases"}
    for _ in range(3):
        try:
            r=requests.get(url,headers=headers,params=params,timeout=20)
            if r.status_code==200:
                time.sleep(SLEEP)
                return r.json()
            if r.status_code in (429,503):
                time.sleep(5)
                continue
            print(f"HTTP {r.status_code} for {mbid}")
            return None
        except Exception as e:
            print(e)
            time.sleep(5)
    return None

def main():
    conn=duckdb.connect(DB_PATH)
    rows=conn.execute("""
        SELECT MBID
        FROM raw.RAW_MUSICBRAINZ_ARTISTS
        WHERE FOUND=TRUE
          AND MBID IS NOT NULL
          AND GENRES IS NULL
        ORDER BY SCORE DESC
    """).fetchall()

    total=len(rows)
    print(f"{total} artists to enrich")

    start=time.time()
    done=ok=err=0

    try:
        for (mbid,) in rows:
            data=api_get(mbid)
            if data:
                genres=json.dumps(data.get("genres",[]))
                tags=json.dumps(data.get("tags",[]))
                aliases=json.dumps(data.get("aliases",[]))
                conn.execute("""
                    UPDATE raw.RAW_MUSICBRAINZ_ARTISTS
                    SET GENRES=?,
                        TAGS=?,
                        ALIASES=?,
                        EXTRACTED_AT=?
                    WHERE MBID=?
                """,[genres,tags,aliases,datetime.now(),mbid])
                ok+=1
            else:
                err+=1

            done+=1

            if done%10==0 or done==total:
                elapsed=time.time()-start
                speed=done/elapsed if elapsed else 0
                remaining=total-done
                eta=timedelta(seconds=int(remaining/speed)) if speed else timedelta()
                pct=done*100/total if total else 100
                print(f"{done}/{total} ({pct:.2f}%) | updated={ok} | errors={err} | speed={speed:.2f} artist/s | ETA={eta}")

            if done%100==0:
                conn.commit()

    except KeyboardInterrupt:
        print("Interrupted. Saving...")
        conn.commit()
        conn.close()
        raise

    conn.commit()
    conn.close()
    print("DONE")

if __name__=="__main__":
    main()
