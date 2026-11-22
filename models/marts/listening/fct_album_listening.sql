/*

    Album listening rollup: listening time per album per calendar month.

    Grain: 1 row = 1 listening month x 1 album, where an album is identified
    by its album artist and album name (the streaming export only provides the
    album_artist_name it carries, not an album id). Two different albums with
    the same name by the same artist would collapse - acceptable here, and the
    track detail stays available in fct_track_listening.

    Reconciliation: exact per month, since a stream belongs to exactly one
    album (guarded by test_fct_album_listening_reconciles). Streams without an
    album name land in the '(unknown)' bucket.

*/

with streams as (

    select
        date_trunc('month', stream_date) as listening_month,
        coalesce(album_name, '(unknown)') as album_name,
        coalesce(artist_name, '(unknown)') as album_artist_name,
        track_id,
        minutes_played,
        skipped

    from {{ ref('fct_streams') }}

)

select

    listening_month,

    album_artist_name,
    album_name,

    round(sum(minutes_played), 6) as total_minutes,
    count(*) as nb_streams,
    count(distinct track_id) as nb_tracks,
    sum(case when skipped then 1 else 0 end) as skipped_streams,

    round(
        sum(case when skipped then 1 else 0 end) / nullif(count(*), 0),
        4
    ) as skip_rate

from streams

group by
    listening_month,
    album_artist_name,
    album_name
