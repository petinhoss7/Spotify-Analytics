-- Consistency between the legacy population flag and the attribution:
-- one_genre_found must be true exactly when a primary genre exists.
select
    artist_id,
    one_genre_found,
    primary_genre
from {{ ref('int_artists') }}
where (one_genre_found and primary_genre is null)
   or (not one_genre_found and primary_genre is not null)
