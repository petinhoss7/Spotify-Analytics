with history as (

    select *
    from {{ ref('stg_spotify_history') }}

)

select

    split_part(spotify_track_uri, ':', 3) as track_id,

    arg_max(track_name, streamed_at) as track_name,
    arg_max(album_name, streamed_at) as album_name,
    arg_max(artist_name, streamed_at) as artist_name,

    count(stream_id) as nb_streams,
    min(streamed_at) as first_streamed_at,
    max(streamed_at) as last_streamed_at

from history
where spotify_track_uri is not null
group by track_id
