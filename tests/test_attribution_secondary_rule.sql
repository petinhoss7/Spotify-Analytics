-- Secondary genre inclusion rule: a secondary genre may only be present
-- when the stored evidence satisfies the configurable thresholds.
select
    artist_id,
    secondary_genre,
    secondary_sources_count,
    secondary_score_ratio
from {{ ref('int_artists_genre_attribution') }}
where secondary_genre is not null
  and (
      secondary_sources_count < {{ var('attribution_min_secondary_sources', 2) }}
      or secondary_score_ratio < {{ var('attribution_min_secondary_score_ratio', 0.5) }}
  )
