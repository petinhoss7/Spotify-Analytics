-- Evidence-proportional shares must be complete: every artist's
-- genre_share values must sum to 1 (they cover ALL their scored
-- genres - this is what lets fct_genre_listening attribute 100% of an
-- artist's listening time).
with shares as (

    select
        artist_id,
        sum(genre_share) as total_share
    from {{ ref('int_artists_genre_scores') }}
    group by artist_id

)

select
    artist_id,
    total_share
from shares
where abs(total_share - 1) > 0.000001
