-- The secondary pair must be real evidence, and distinct from the primary.
-- When it is present it must pass the inclusion rule: at least
-- attribution_min_secondary_tags distinct tags backing it, or at least
-- attribution_min_secondary_score_ratio of the primary score. This is what
-- stops a single stray tag (an isolated "pop", "orchestral" or "black metal")
-- from inventing a second genre.
select
    artist_id,
    primary_genre,
    secondary_genre,
    secondary_nb_tags,
    secondary_score_ratio
from {{ ref('int_artists_genre_attribution') }}
where secondary_genre is not null
  and (
      secondary_genre = primary_genre
      or (
          secondary_nb_tags < {{ var('attribution_min_secondary_tags', 2) }}
          and secondary_score_ratio < {{ var('attribution_min_secondary_score_ratio', 0.10) }}
      )
  )
