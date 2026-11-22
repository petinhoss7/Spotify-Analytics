-- Reconciliation: a stream belongs to exactly one album, so per month the
-- album minutes must equal the month's listening minutes exactly.
with mart as (

    select
        listening_month,
        sum(total_minutes) as minutes
    from {{ ref('fct_album_listening') }}
    group by listening_month

),

source as (

    select
        date_trunc('month', stream_date) as listening_month,
        sum(minutes_played) as minutes
    from {{ ref('fct_streams') }}
    group by date_trunc('month', stream_date)

)

select
    coalesce(m.listening_month, s.listening_month) as listening_month,
    m.minutes as mart_minutes,
    s.minutes as source_minutes
from mart m

full outer join source s
    using (listening_month)

where m.listening_month is null
   or s.listening_month is null
   or abs(m.minutes - s.minutes) > 0.01
