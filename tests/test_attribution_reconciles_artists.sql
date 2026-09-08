-- Grain reconciliation: every artist genre-classified in the line-by-line
-- model must appear exactly once in the attribution, and no extra artist.
with expected as (

    select distinct artist_id
    from {{ ref('int_source_tag_classification') }}
    where classification_status = 'genre'

),

actual as (

    select artist_id
    from {{ ref('int_artists_genre_attribution') }}

)

select
    coalesce(e.artist_id, a.artist_id) as artist_id,
    case
        when e.artist_id is null then 'extra_in_attribution'
        else 'missing_from_attribution'
    end as issue
from expected e
full outer join actual a
    using (artist_id)
where e.artist_id is null
   or a.artist_id is null
