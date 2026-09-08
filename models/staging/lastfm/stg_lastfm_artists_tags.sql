{{ config(materialized='view') }}

with artists as (

    select

        artist_id,
        spotify_artist_name,
        lastfm_tags

    from {{ ref('stg_lastfm_artists') }}

    where found = true
      and lastfm_tags is not null
      and trim(lastfm_tags) <> '[]'

),

tags as (

    select

        artist_id,
        spotify_artist_name,

        unnest(
            from_json(
                lastfm_tags,
                '["JSON"]'
            )
        ) as tag_json

    from artists

)

select

    artist_id,

    spotify_artist_name,

    json_extract_string(tag_json, '$.name') as tag_name,

    cast(
        json_extract(tag_json, '$.count')
        as integer
    ) as tag_count

from tags

qualify row_number() over (
    partition by artist_id, tag_name
    order by tag_count desc
) = 1