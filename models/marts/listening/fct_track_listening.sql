/*

    Track listening rollup: listening time per track per calendar month.

    Grain: 1 row = 1 listening month x 1 track.

    Unlike the artist and genre marts there is no split here: a stream belongs
    to exactly one track, so the minutes are whole. That is what makes the
    monthly reconciliation exact (guarded by
    test_fct_track_listening_reconciles): every stream of fct_streams lands in
    exactly one row.

    Behaviour columns (skipped, meaningful listen) describe how the track was
    listened to that month, which is where a "skip rate" by track is read
    from: skipped_streams / nb_streams.

*/

with streams as (

    select
        date_trunc('month', stream_date) as listening_month,
        track_id,
        minutes_played,
        ms_played,
        is_meaningful_listen,
        skipped,
        streamed_at

    from {{ ref('fct_streams') }}

),

aggregated as (

    select
        listening_month,
        track_id,
        sum(minutes_played) as total_minutes,
        count(*) as nb_streams,
        sum(case when is_meaningful_listen then 1 else 0 end) as meaningful_streams,
        sum(case when skipped then 1 else 0 end) as skipped_streams,
        min(streamed_at) as first_streamed_at,
        max(streamed_at) as last_streamed_at

    from streams
    group by
        listening_month,
        track_id

),

details as (

    select
        track_id,
        track_name,
        album_name,
        artist_name

    from {{ ref('int_tracks_base') }}

)

select

    a.listening_month,
    a.track_id,

    d.track_name,
    d.album_name,
    d.artist_name,

    round(a.total_minutes, 6) as total_minutes,
    a.nb_streams,
    a.meaningful_streams,
    a.skipped_streams,

    round(
        a.skipped_streams / nullif(a.nb_streams, 0),
        4
    ) as skip_rate,

    a.first_streamed_at,
    a.last_streamed_at

from aggregated a

left join details d
    on d.track_id = a.track_id
