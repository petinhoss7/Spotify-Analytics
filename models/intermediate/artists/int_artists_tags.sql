/*

    All artist tags from the 3 sources, classified against the closed
    Discogs taxonomy (seeds/discogs_genres_styles.json).

    Classification is produced offline by scripts/classifier/classify_tags.py
    and materialized as the tag_genre_map seed. This model only applies it:
        - 1 row = 1 artist x 1 raw tag that mapped to a Discogs genre
        - tags classified as non-genre (is_genre_tag = false) are excluded
        - tags missing from the map are excluded; the singular test
          test_staging_tags_all_mapped.sql guards against gaps

    discogs_genre : closed-list genre (15 values, acts as the genre family)
    discogs_style : closed-list style/sous-genre (372 values), may be null
                    when no specific style fits the raw tag

*/

with spotify as (

    select
        artist_id,
        'rapidapi' as source,
        tag_name as original_tag
    from {{ ref('stg_spotify_artists_tags') }}

),

lastfm as (

    select
        artist_id,
        'lastfm' as source,
        tag_name as original_tag
    from {{ ref('stg_lastfm_artists_tags') }}

),

musicbrainz as (

    select
        artist_id,
        'musicbrainz' as source,
        tag_name as original_tag
    from {{ ref('stg_musicbrainz_artists_tags') }}

),

all_tags as (

    select * from spotify

    union all

    select * from lastfm

    union all

    select * from musicbrainz

),

classified as (

    select
        t.artist_id,
        t.source,
        t.original_tag,
        m.discogs_genre,
        m.discogs_style
    from all_tags t
    inner join {{ ref('tag_genre_map') }} m
        on lower(trim(t.original_tag)) = m.raw_tag
    where m.is_genre_tag

)

select * from classified
