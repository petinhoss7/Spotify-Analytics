with

    source as (

        select raw_record, file_name, load_timestamp
        from {{ source("spotify_history", "raw_spotify_streaming") }}

    ),

    flattened as (

        select
            -- Surrogate key
            {{
                dbt_utils.generate_surrogate_key(
                    [
                        "raw_record:spotify_track_uri::STRING",
                        "raw_record:ts::STRING",
                        "raw_record:ms_played::STRING",
                    ]
                )
            }} as stream_id,

            -- Timestamps
            raw_record:ts::timestamp_ntz as streamed_at,

            -- Track metadata
            raw_record:master_metadata_track_name::string as track_name,
            raw_record:master_metadata_album_artist_name::string as artist_name,
            raw_record:master_metadata_album_album_name::string as album_name,
            raw_record:spotify_track_uri::string as spotify_track_uri,

            -- Playback metrics
            raw_record:ms_played::integer as ms_played,
            raw_record:ms_played::float / 60000.0 as minutes_played,

            -- Playback context
            raw_record:platform::string as platform,
            raw_record:conn_country::string as conn_country,
            raw_record:reason_start::string as reason_start,
            raw_record:reason_end::string as reason_end,
            raw_record:shuffle::boolean as shuffle,
            raw_record:skipped::boolean as skipped,
            raw_record:offline::boolean as offline,
            raw_record:offline_timestamp::string as offline_timestamp,
            raw_record:incognito_mode::boolean as incognito_mode,
            raw_record:ip_addr::string as ip_addr,

            -- Podcast fields
            raw_record:episode_name::string as episode_name,
            raw_record:episode_show_name::string as episode_show_name,
            raw_record:spotify_episode_uri::string as spotify_episode_uri,

            -- Audiobook fields
            raw_record:audiobook_title::string as audiobook_title,
            raw_record:audiobook_chapter_title::string as audiobook_chapter_title,
            raw_record:audiobook_uri::string as audiobook_uri,
            raw_record:audiobook_chapter_uri::string as audiobook_chapter_uri,

            -- Content type flags
            raw_record:episode_name::string is not null as is_podcast,
            raw_record:audiobook_title::string is not null as is_audiobook,

            -- Source lineage
            file_name as source_file_name,
            load_timestamp as loaded_at

        from source

    )

select *
from flattened
