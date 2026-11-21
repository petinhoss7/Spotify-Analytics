-- Reconciliation: fct_streams must contain every music stream exactly
-- once, with unchanged listening minutes. Any missing / extra stream or
-- drifted minute value is a defect.
with fct as (

    select
        stream_id,
        minutes_played
    from {{ ref('fct_streams') }}

),

source as (

    select
        stream_id,
        minutes_played
    from {{ ref('int_spotify_streams_enriched') }}

)

select
    coalesce(f.stream_id, s.stream_id) as stream_id,
    f.minutes_played as fct_minutes,
    s.minutes_played as source_minutes
from fct f

full outer join source s
    using (stream_id)

where f.stream_id is null
   or s.stream_id is null
   or abs(f.minutes_played - s.minutes_played) > 0.0001
