{{ config(materialized='view') }}

with source as (

    select *
    from {{ source('lastfm', 'RAW_LASTFM_ARTIST_GENRES') }}

)

select

    artist_id,

    trim(spotify_artist_name) as spotify_artist_name,

    nullif(trim(lastfm_artist_name), '') as lastfm_artist_name,

    cast(lastfm_tags as json) as lastfm_tags,

    json_array_length(lastfm_tags) as lastfm_tag_count,

    case
        when json_array_length(lastfm_tags) > 0
        then json_extract_string(lastfm_tags, '$[0].name')
    end as lastfm_primary_tag,

    found,

    extracted_at

from source