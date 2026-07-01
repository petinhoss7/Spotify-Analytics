with deduped as (
    
    select * from {{ref('int_spotify_streams_deduped')}}
),

enriched as (
    
    select 
    deduped.stream_id,
    deduped.streamed_at,
    deduped.track_name,
    deduped.artist_name,
    deduped.album_name,
    deduped.spotify_track_uri,
    deduped.ms_played,
    deduped.minutes_played,
    deduped.platform,
    deduped.conn_country,
    deduped.reason_start,
    deduped.reason_end,
    deduped.shuffle,
    deduped.skipped,
    deduped.offline,
    deduped.offline_timestamp,
    deduped.incognito_mode,
    deduped.ip_addr,
    deduped.is_podcast,
    deduped.is_audiobook,
    deduped.source_file_name,
    deduped.loaded_at,
    deduped.rank,
    case
        when deduped.ms_played >= 30000 then TRUE
        else FALSE
    end as is_meaningful_listen,
    extract(hour from deduped.streamed_at) as listening_hour,
    dayname(deduped.streamed_at) as listening_date

    from deduped
    where (deduped.is_podcast = FALSE) and (deduped.is_audiobook = FALSE)
)

select * from enriched
