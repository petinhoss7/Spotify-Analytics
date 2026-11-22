/*

    Artist-level split of each stream's listening time.

    Grain: 1 row = 1 stream x 1 artist of the track.

    A stream's minutes are divided by the number of artists on the track, so
    the sum over a stream's artists equals the stream's minutes - dividing
    rather than duplicating is what keeps the artist figures additive.

    Unlike int_stream_artist_pairs, this model keeps EVERY artist of the
    bridge, including those without a genre attribution: the artist-level
    marts must not lose them. int_stream_artist_pairs builds on it and adds
    the genre/style allocation.

*/

with streams as (

    -- the stream fact, so the track_id derivation is defined in one place
    select
        stream_id,
        stream_date,
        track_id,
        minutes_played

    from {{ ref('fct_streams') }}

),

track_artists as (

    select
        track_id,
        artist_id,
        artist_count

    from {{ ref('int_tracks_artists') }}

)

select

    s.stream_id,
    s.stream_date,
    s.track_id,

    ta.artist_id,
    ta.artist_count,

    s.minutes_played / ta.artist_count as artist_minutes,
    1.0 / ta.artist_count as artist_stream_fraction

from streams s

inner join track_artists ta
    on s.track_id = ta.track_id
