with source as (

    select 
        track_uri,
        raw_audio_features::JSON as raw_audio_features,
        loaded_at
    from {{ source("rapidapi", "RAW_SPOTIFY_AUDIO_FEATURES") }}

),

flattened as (

    select

        track_uri,

        -- Confidence the track is acoustic (0.0-1.0)
        cast(json_extract_string(raw_audio_features, '$.acousticness') as float) as acousticness,

        -- URL of the full audio-analysis resource for the track
        json_extract_string(raw_audio_features, '$.analysis_url') as analysis_url,

        -- How suitable the track is for dancing (0.0-1.0)
        cast(json_extract_string(raw_audio_features, '$.danceability') as float) as danceability,

        -- The track length in milliseconds
        cast(json_extract_string(raw_audio_features, '$.duration_ms') as integer) as duration_ms,

        -- Perceptual measure of intensity and activity (0.0-1.0)
        cast(json_extract_string(raw_audio_features, '$.energy') as float) as energy,

        -- The 22-character Spotify ID of the track
        json_extract_string(raw_audio_features, '$.id') as track_id,

        -- Likelihood the track contains no vocals (0.0-1.0)
        cast(json_extract_string(raw_audio_features, '$.instrumentalness') as float) as instrumentalness,

        -- Estimated overall key (0-11, -1 if none detected)
        cast(json_extract_string(raw_audio_features, '$.key') as integer) as musical_key,

        -- Probability the track was performed live (0.0-1.0)
        cast(json_extract_string(raw_audio_features, '$.liveness') as float) as liveness,

        -- Overall loudness in decibels
        cast(json_extract_string(raw_audio_features, '$.loudness') as float) as loudness,

        -- Modality (0 = minor, 1 = major)
        cast(json_extract_string(raw_audio_features, '$.mode') as integer) as mode,

        -- Presence of spoken words (0.0-1.0)
        cast(json_extract_string(raw_audio_features, '$.speechiness') as float) as speechiness,

        -- Estimated tempo in beats per minute
        cast(json_extract_string(raw_audio_features, '$.tempo') as float) as tempo,

        -- Estimated time signature (beats per bar)
        cast(json_extract_string(raw_audio_features, '$.time_signature') as integer) as time_signature,

        -- Link to the full track object
        json_extract_string(raw_audio_features, '$.track_href') as track_href,

        -- Object type (always "audio_features")
        json_extract_string(raw_audio_features, '$.type') as object_type,

        -- Spotify URI
        json_extract_string(raw_audio_features, '$.uri') as spotify_uri,

        -- Musical positiveness (0.0-1.0)
        cast(json_extract_string(raw_audio_features, '$.valence') as float) as valence,

        loaded_at

    from source

)

select *
from flattened
qualify row_number() over (
    partition by track_uri
    order by loaded_at desc
) = 1