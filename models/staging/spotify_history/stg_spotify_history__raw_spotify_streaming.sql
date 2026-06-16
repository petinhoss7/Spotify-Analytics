with 

source as (

    select  raw_record, 
            file_name,
            load_timestamp
    from {{ source('spotify_history', 'raw_spotify_streaming') }}

),

flattened as (

    select
         -- Surrogate key
        {{ dbt_utils.generate_surrogate_key([
            "raw_record:spotify_track_uri::STRING",
            "raw_record:ts::STRING",
            "raw_record:ms_played::STRING"
        ]) }} AS stream_id,

         -- Timestamps
        raw_record:ts::TIMESTAMP_NTZ AS streamed_at,

          -- Track metadata
        raw_record:master_metadata_track_name::STRING AS track_name,
        raw_record:master_metadata_album_artist_name::STRING AS artist_name,
        raw_record:master_metadata_album_album_name::STRING AS album_name,
        raw_record:spotify_track_uri::STRING AS spotify_track_uri,

        -- Playback metrics
        raw_record:ms_played::INTEGER AS ms_played,
        raw_record:ms_played::FLOAT / 60000.0 AS minutes_played,

        -- Playback context
        raw_record:platform::STRING AS platform,
        raw_record:conn_country::STRING AS conn_country,
        raw_record:reason_start::STRING AS reason_start,
        raw_record:reason_end::STRING AS reason_end,
        raw_record:shuffle::BOOLEAN AS shuffle,
        raw_record:skipped::BOOLEAN AS skipped,
        raw_record:offline::BOOLEAN AS offline,
        raw_record:offline_timestamp::STRING AS offline_timestamp,
        raw_record:incognito_mode::BOOLEAN AS incognito_mode,
        raw_record:ip_addr::STRING AS ip_addr,

         -- Podcast fields
        raw_record:episode_name::STRING AS episode_name,
        raw_record:episode_show_name::STRING AS episode_show_name,
        raw_record:spotify_episode_uri::STRING AS spotify_episode_uri,

        -- Audiobook fields
        raw_record:audiobook_title::STRING AS audiobook_title,
        raw_record:audiobook_chapter_title::STRING AS audiobook_chapter_title,
        raw_record:audiobook_uri::STRING AS audiobook_uri,
        raw_record:audiobook_chapter_uri::STRING AS audiobook_chapter_uri,

        -- Content type flags
        raw_record:episode_name::STRING IS NOT NULL AS is_podcast,
        raw_record:audiobook_title::STRING IS NOT NULL AS is_audiobook,

        -- Source lineage
        FILE_NAME AS source_file_name,
        LOAD_TIMESTAMP AS loaded_at

    from source

)

select * from flattened