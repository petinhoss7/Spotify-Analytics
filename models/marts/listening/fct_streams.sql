/*

    Event fact: one row per music stream.

    Grain: 1 row = 1 music stream (podcasts / audiobooks excluded
    upstream in int_spotify_streams_enriched). Row count and listening
    minutes must reconcile with int_spotify_streams_enriched - guarded
    by test_fct_streams_reconciles. Pipeline metadata columns
    (source_file_name, loaded_at, ip_addr_hash, incognito_mode) stay in
    the intermediate layer; join back on stream_id if needed.

    Attribution convenience columns (denormalized for analysis):

        - track_id: Spotify track id derived from the track uri
        - lead_artist_id / lead_artist_name: the track-artist whose name
          matches the stream's artist_name, deterministic fallback on
          the lowest artist_id when no name matches (multi-artist
          tracks). Null when the track is absent from the bridge.
        - is_lead_name_match: whether the lead artist was picked by
          name match (false = fallback or unmapped track)
        - artist_count / is_collaboration: bridge fan-out metadata,
          null when the track is absent from the bridge
        - lead_primary_genre: sanctioned primary genre of the lead
          artist (int_artists). This is NOT the evidence-proportional
          attribution used by fct_genre_listening.

*/

with streams as (

    select

        stream_id,
        stream_date,
        streamed_at,
        listening_hour,
        listening_day_of_week,

        track_name,
        album_name,
        artist_name,
        split_part(spotify_track_uri, ':', 3) as track_id,

        ms_played,
        minutes_played,
        is_meaningful_listen,

        platform,
        conn_country,
        reason_start,
        reason_end,
        shuffle,
        skipped,
        offline

    from {{ ref('int_spotify_streams_enriched') }}

),

joined as (

    select
        s.*,
        b.artist_id as candidate_artist_id,
        b.artist_name as candidate_artist_name,
        b.artist_count,
        b.is_collaboration,
        case
            when lower(b.artist_name) = lower(s.artist_name) then 0
            else 1
        end as name_match_rank

    from streams s

    left join {{ ref('int_tracks_artists') }} b
        on s.track_id = b.track_id

),

lead as (

    select
        * exclude (name_match_rank)

    from joined
    qualify row_number() over (
        partition by stream_id
        order by
            name_match_rank,
            candidate_artist_id
    ) = 1

)

select

    l.stream_id,

    l.stream_date,
    l.streamed_at,
    l.listening_hour,
    l.listening_day_of_week,

    l.track_id,
    l.track_name,
    l.album_name,
    l.artist_name,

    l.candidate_artist_id as lead_artist_id,
    l.candidate_artist_name as lead_artist_name,

    coalesce(lower(l.candidate_artist_name) = lower(l.artist_name), false)
        as is_lead_name_match,

    l.artist_count,
    l.is_collaboration,

    a.primary_genre as lead_primary_genre,

    l.ms_played,
    l.minutes_played,
    l.is_meaningful_listen,

    l.platform,
    l.conn_country,
    l.reason_start,
    l.reason_end,

    l.shuffle,
    l.skipped,
    l.offline

from lead l

left join {{ ref('int_artists') }} a
    on l.candidate_artist_id = a.artist_id
