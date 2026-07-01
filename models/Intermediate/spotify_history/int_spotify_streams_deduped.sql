with unduped as (
    
    select * from {{ref('stg_spotify_history__raw_spotify_streaming')}}
),

ranked_rows as (
    
    select 
    unduped.stream_id,
    unduped.streamed_at,
    unduped.track_name,
    unduped.artist_name,
    unduped.album_name,
    unduped.spotify_track_uri,
    unduped.ms_played,
    unduped.minutes_played,
    unduped.platform,
    unduped.conn_country,
    unduped.reason_start,
    unduped.reason_end,
    unduped.shuffle,
    unduped.skipped,
    unduped.offline,
    unduped.offline_timestamp,
    unduped.incognito_mode,
    unduped.ip_addr,
    unduped.is_podcast,
    unduped.is_audiobook,
    unduped.source_file_name,
    unduped.loaded_at,
    row_number() over (
        partition by unduped.stream_id
        order by unduped.loaded_at desc
    ) as rank
    from unduped
)

select * from ranked_rows where rank = 1