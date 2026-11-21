with deduped as (

    select * from {{ ref('int_spotify_streams_deduped') }}

)

select

    stream_id,

    cast(streamed_at as date) as stream_date,
    streamed_at,

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

    is_podcast,
    is_audiobook,

    source_file_name,
    loaded_at,

    ms_played >= 30000 as is_meaningful_listen,
    extract(hour from streamed_at) as listening_hour,
    dayname(streamed_at) as listening_day_of_week

from deduped
where is_podcast = FALSE
  and is_audiobook = FALSE
