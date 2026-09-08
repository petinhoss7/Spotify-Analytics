-- Every staging tag (excluding empty) must be present in the tag map,
-- otherwise the inner join in int_artists_tags silently drops tags.
with staging_tags as (

    select distinct lower(trim(tag_name)) as raw_tag
    from {{ ref('stg_lastfm_artists_tags') }}
    where trim(tag_name) <> ''

    union

    select distinct lower(trim(tag_name)) as raw_tag
    from {{ ref('stg_musicbrainz_artists_tags') }}
    where trim(tag_name) <> ''

    union

    select distinct lower(trim(tag_name)) as raw_tag
    from {{ ref('stg_spotify_artists_tags') }}
    where trim(tag_name) <> ''

)

select
    s.raw_tag
from staging_tags s
left join {{ ref('tag_genre_map') }} m
    on s.raw_tag = m.raw_tag
where m.raw_tag is null
