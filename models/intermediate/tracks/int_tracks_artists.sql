with track_artists as (

    select
        track_id,
        artist_id
    from {{ ref('stg_spotify_track_artists') }}

),

artist_counts as (

    select
        track_id,
        count(distinct artist_id) as artist_count
    from track_artists
    group by track_id

),

artists as (

    select
        artist_id,
        spotify_artist_name,
        primary_genre,
        secondary_genre,
        primary_style,
        secondary_style
    from {{ ref('int_artists') }}

),

tracks as (

    select
        track_id,
        track_name
    from {{ ref('int_tracks_base') }}

)

select

    ta.track_id,

    t.track_name,

    ta.artist_id,
    a.spotify_artist_name as artist_name,

    a.primary_genre,
    a.secondary_genre,
    a.primary_style,
    a.secondary_style,

    ac.artist_count,

    case
        when ac.artist_count > 1 then true
        else false
    end as is_collaboration

from track_artists ta

left join tracks t
    using (track_id)

left join artists a
    using (artist_id)

left join artist_counts ac
    using (track_id)