-- The attribution model must consume the same genre scores as the
-- listening marts: every stored primary_genre_score must equal the
-- genre_score of that genre in int_artists_genre_scores (small
-- tolerance: attribution stores scores rounded to 3 decimals).
select
    a.artist_id,
    a.primary_genre,
    a.primary_genre_score,
    s.genre_score
from {{ ref('int_artists_genre_attribution') }} a

join {{ ref('int_artists_genre_scores') }} s
    on a.artist_id = s.artist_id
   and a.primary_genre = s.discogs_genre

where abs(a.primary_genre_score - s.genre_score) > 0.001
