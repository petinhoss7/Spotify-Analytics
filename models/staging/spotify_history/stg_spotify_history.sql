with source as (

    select
        raw_record::JSON as raw_record,
        file_name,
        load_timestamp
    from {{ source("spotify_history", "RAW_SPOTIFY_STREAMING") }}

),

extracted as (

    select

        {{
            dbt_utils.generate_surrogate_key(
                [
                    "json_extract_string(raw_record, '$.spotify_track_uri')",
                    "json_extract_string(raw_record, '$.ts')",
                    "json_extract_string(raw_record, '$.ms_played')"
                ]
            )
        }} as stream_id,

        json_extract_string(raw_record, '$.ts') as ts_raw,

        json_extract_string(raw_record, '$.master_metadata_track_name') as track_name,
        json_extract_string(raw_record, '$.master_metadata_album_artist_name') as artist_name,
        json_extract_string(raw_record, '$.master_metadata_album_album_name') as album_name,
        json_extract_string(raw_record, '$.spotify_track_uri') as spotify_track_uri,

        cast(json_extract_string(raw_record, '$.ms_played') as integer) as ms_played,
        cast(json_extract_string(raw_record, '$.ms_played') as float) / 60000.0 as minutes_played,

        json_extract_string(raw_record, '$.platform') as platform,
        json_extract_string(raw_record, '$.conn_country') as conn_country,
        json_extract_string(raw_record, '$.reason_start') as reason_start,
        json_extract_string(raw_record, '$.reason_end') as reason_end,

        cast(json_extract_string(raw_record, '$.shuffle') as boolean) as shuffle,
        cast(json_extract_string(raw_record, '$.skipped') as boolean) as skipped,
        cast(json_extract_string(raw_record, '$.offline') as boolean) as offline,

        json_extract_string(raw_record, '$.offline_timestamp') as offline_timestamp,
        cast(json_extract_string(raw_record, '$.incognito_mode') as boolean) as incognito_mode,
        md5(json_extract_string(raw_record, '$.ip_addr')) as ip_addr_hash,

        json_extract_string(raw_record, '$.episode_name') as episode_name,
        json_extract_string(raw_record, '$.episode_show_name') as episode_show_name,
        json_extract_string(raw_record, '$.spotify_episode_uri') as spotify_episode_uri,

        json_extract_string(raw_record, '$.audiobook_title') as audiobook_title,
        json_extract_string(raw_record, '$.audiobook_chapter_title') as audiobook_chapter_title,
        json_extract_string(raw_record, '$.audiobook_uri') as audiobook_uri,
        json_extract_string(raw_record, '$.audiobook_chapter_uri') as audiobook_chapter_uri,

        json_extract_string(raw_record, '$.episode_name') is not null as is_podcast,
        json_extract_string(raw_record, '$.audiobook_title') is not null as is_audiobook,

        file_name as source_file_name,
        load_timestamp as loaded_at

    from source

)

select

    stream_id,

    case
        when regexp_matches(ts_raw, '(Z|[+-][0-9]{2}:?[0-9]{2})$')
            then try_cast(ts_raw as timestamptz) at time zone 'UTC'
        else try_cast(ts_raw as timestamp)
    end as streamed_at,

    track_name,
    artist_name,
    album_name,
    spotify_track_uri,

    ms_played,
    minutes_played,

    platform,
    conn_country,
    reason_start,
    reason_end,

    shuffle,
    skipped,
    offline,

    offline_timestamp,
    incognito_mode,
    ip_addr_hash,

    episode_name,
    episode_show_name,
    spotify_episode_uri,

    audiobook_title,
    audiobook_chapter_title,
    audiobook_uri,
    audiobook_chapter_uri,

    is_podcast,
    is_audiobook,

    source_file_name,
    loaded_at

from extracted
