{{ config(materialized='view') }}

with artists as (

    select
        artist_id,
        spotify_artist_name,
        tags

    from {{ ref('stg_musicbrainz_artists') }}

    where found = true
      and tags is not null
      and trim(tags) <> '[]'

),

flattened_tags as (

    select
        artist_id,
        spotify_artist_name,
        unnest(
            from_json(tags, '["JSON"]')
        ) as tag_json

    from artists

),

parsed_tags as (

    select

        artist_id,

        spotify_artist_name,

        case
            when json_type(tag_json) = 'OBJECT'
                then json_extract_string(tag_json, '$.name')
            else
                trim(both '"' from tag_json::varchar)
        end as tag_name,

        case
            when json_type(tag_json) = 'OBJECT'
                then cast(json_extract(tag_json, '$.count') as integer)
            else
                null
        end as tag_count

    from flattened_tags

)

select *

from parsed_tags

where tag_name is not null
  and trim(tag_name) <> ''