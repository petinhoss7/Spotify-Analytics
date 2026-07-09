with

    source as (

        select track_uri, raw_audio_features, loaded_at
        from {{ source("audio_features", "raw_spotify_audio_features") }}

    ),

    flattened as (

        select
            track_uri,

            -- Confidence the track is acoustic (0.0-1.0)
            raw_audio_features:acousticness::float          AS acousticness,

            -- URL of the full audio-analysis resource for the track
            raw_audio_features:analysis_url::string         AS analysis_url,

            -- How suitable the track is for dancing (0.0-1.0)
            raw_audio_features:danceability::float          AS danceability,

            -- The track length in milliseconds
            raw_audio_features:duration_ms::integer         AS duration_ms,

            -- Perceptual measure of intensity and activity (0.0-1.0)
            raw_audio_features:energy::float                AS energy,

            -- The 22-character Spotify ID of the track
            raw_audio_features:id::string                   AS track_id,

            -- Likelihood the track contains no vocals (0.0-1.0)
            raw_audio_features:instrumentalness::float      AS instrumentalness,

            -- Estimated overall key (0-11, -1 if none detected)
            raw_audio_features:key::integer                 AS musical_key,

            -- Probability the track was performed live (0.0-1.0)
            raw_audio_features:liveness::float              AS liveness,

            -- Overall loudness in decibels
            raw_audio_features:loudness::float              AS loudness,

            -- Modality (0 = minor, 1 = major)
            raw_audio_features:mode::integer                AS mode,

            -- Presence of spoken words (0.0-1.0)
            raw_audio_features:speechiness::float           AS speechiness,

            -- Estimated tempo in beats per minute
            raw_audio_features:tempo::float                 AS tempo,

            -- Estimated time signature (beats per bar)
            raw_audio_features:time_signature::integer      AS time_signature,

            -- Link to the full track object
            raw_audio_features:track_href::string           AS track_href,

            -- Object type (always "audio_features")
            raw_audio_features:type::string                 AS object_type,

            -- Spotify URI
            raw_audio_features:uri::string                  AS spotify_uri,

            -- Musical positiveness (0.0-1.0)
            raw_audio_features:valence::float               AS valence,

            loaded_at

        from source

    )

select *
from flattened
