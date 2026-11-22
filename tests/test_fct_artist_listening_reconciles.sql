-- Reconciliation: per month, the minutes credited to artists must equal the
-- minutes of the streams that have an artist at all. The difference with the
-- month's grand total is exactly the streams whose track is absent from the
-- bridge (no artist to credit), which fct_genre_listening carries in its
-- 'no_artist_data' bucket.
with mart as (

    select
        listening_month,
        sum(total_minutes) as minutes
    from {{ ref('fct_artist_listening') }}
    group by listening_month

),

expected as (

    select
        date_trunc('month', f.stream_date) as listening_month,
        sum(f.minutes_played / b.artist_count) as minutes
    from {{ ref('fct_streams') }} f
    inner join {{ ref('int_tracks_artists') }} b
        on f.track_id = b.track_id
    group by date_trunc('month', f.stream_date)

)

select
    coalesce(m.listening_month, e.listening_month) as listening_month,
    m.minutes as mart_minutes,
    e.minutes as expected_minutes
from mart m

full outer join expected e
    using (listening_month)

where m.listening_month is null
   or e.listening_month is null
   or abs(m.minutes - e.minutes) > 0.01
