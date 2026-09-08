import requests
import os
from dotenv import load_dotenv

load_dotenv()

params = {
    "method": "artist.getTopTags",
    "artist": "Benny Golson",
    "api_key": os.getenv("LASTFM_API_KEY"),
    "format": "json"
}

r = requests.get(
    "https://ws.audioscrobbler.com/2.0/",
    params=params
)

print(r.url)
print(r.status_code)
print(r.text)