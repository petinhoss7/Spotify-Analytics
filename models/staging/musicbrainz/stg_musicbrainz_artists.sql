{{ config(materialized='view') }}

select

    artist_id,

    trim(spotify_artist_name) as spotify_artist_name,

    trim(search_name) as search_name,

    found,

    score,

    mbid,

    trim(musicbrainz_name) as musicbrainz_artist_name,

    trim(sort_name) as sort_name,

    trim(disambiguation) as disambiguation,

    trim(artist_type) as artist_type,

    artist_type_id,

    trim(gender) as gender,

    upper(trim(country)) as country,

    trim(area) as area,

    begin_date,

    end_date,

    ended,

    genres,

    tags,

    aliases,

    trim(error_message) as error_message,

    extracted_at

from {{ source('musicbrainz', 'RAW_MUSICBRAINZ_ARTISTS') }}

-- The genres and aliases JSON arrays are preserved for completeness.
-- Only tags are flattened into a dedicated staging model, as they provide
-- the richest descriptive metadata for analytics.