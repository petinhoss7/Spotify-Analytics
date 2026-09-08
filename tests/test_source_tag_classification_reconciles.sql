-- Reconciliation: the line-by-line model must contain exactly the staging
-- rows of the 3 sources - the map join neither drops nor duplicates lines.
with expected as (

    select 'lastfm' as source, count(*) as n
    from {{ ref('stg_lastfm_artists_tags') }}

    union all

    select 'musicbrainz' as source, count(*) as n
    from {{ ref('stg_musicbrainz_artists_tags') }}

    union all

    select 'rapidapi' as source, count(*) as n
    from {{ ref('stg_spotify_artists_tags') }}

),

actual as (

    select source, count(*) as n
    from {{ ref('int_source_tag_classification') }}
    group by source

)

select
    coalesce(e.source, a.source) as source,
    e.n as expected_rows,
    a.n as actual_rows
from expected e
full outer join actual a
    using (source)
where e.n is distinct from a.n
