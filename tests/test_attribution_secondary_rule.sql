-- The combination must be complete: an artist with at least two scored genres
-- must carry a secondary genre, and it must be a different genre from the
-- primary one. A missing secondary genre for such an artist means the
-- combination is incomplete, which the model no longer allows.
select
    artist_id,
    primary_genre,
    secondary_genre,
    nb_distinct_genres
from {{ ref('int_artists_genre_attribution') }}
where (nb_distinct_genres >= 2 and secondary_genre is null)
   or (secondary_genre is not null and secondary_genre = primary_genre)
