with tracks as (

    select *
    from {{ ref('int_tracks_base') }}

),

audio_features as (

    select *
    from {{ ref('stg_audio_features') }}

)

select

    -- Track
    t.track_id,
    t.track_name,
    t.album_name,
    t.artist_name,
    t.nb_streams,
    t.first_streamed_at,
    t.last_streamed_at,

    -- Audio features
    af.duration_ms,
    af.danceability,
    af.energy,
    af.musical_key,
    af.loudness,
    af.mode,
    af.speechiness,
    af.acousticness,
    af.instrumentalness,
    af.liveness,
    af.valence,
    af.tempo,
    af.time_signature

from tracks t

left join audio_features af
    on t.track_id = af.track_id