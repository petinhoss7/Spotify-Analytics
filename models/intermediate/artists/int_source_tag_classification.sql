/*

    Line-by-line source tag classification.

    Grain: 1 row = 1 artist x 1 source x 1 raw staging tag.
    Faithful union of the 3 staging tag views (nothing deduplicated,
    nothing filtered) left-joined to the tag_genre_map seed so that
    every staging line is visible with its classification outcome.

    classification_status:
        - 'genre'     : tag mapped to a Discogs genre
        - 'non_genre' : tag explicitly classified as not a genre
                        (nationality, decade, artist name, ...)
        - 'empty_tag' : blank tag from the source (kept for
                        row-count reconciliation)
        - 'unmapped'  : tag missing from the map - must always be
                        0 rows, guarded by test_source_tag_classification_no_unmapped

*/

with lastfm as (

    select
        artist_id,
        spotify_artist_name,
        'lastfm' as source,
        tag_name,
        tag_count
    from {{ ref('stg_lastfm_artists_tags') }}

),

musicbrainz as (

    select
        artist_id,
        spotify_artist_name,
        'musicbrainz' as source,
        tag_name,
        tag_count
    from {{ ref('stg_musicbrainz_artists_tags') }}

),

rapidapi as (

    select
        artist_id,
        artist_name as spotify_artist_name,
        'rapidapi' as source,
        tag_name,
        cast(null as integer) as tag_count
    from {{ ref('stg_spotify_artists_tags') }}

),

all_tags as (

    select * from lastfm

    union all

    select * from musicbrainz

    union all

    select * from rapidapi

),

classified as (

    select
        t.artist_id,
        t.spotify_artist_name,
        t.source,
        t.tag_name,
        t.tag_count,
        lower(trim(t.tag_name)) as raw_tag,
        m.is_genre_tag,
        m.discogs_genre,
        m.discogs_style,
        m.match_method,
        m.match_score,
        case
            when trim(t.tag_name) = '' then 'empty_tag'
            when m.raw_tag is null then 'unmapped'
            when m.is_genre_tag then 'genre'
            else 'non_genre'
        end as classification_status

    from all_tags t

    left join {{ ref('tag_genre_map') }} m
        on lower(trim(t.tag_name)) = m.raw_tag

)

select * from classified
