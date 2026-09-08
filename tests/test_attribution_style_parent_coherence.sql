-- Style-parent coherence: each attributed style must be a valid
-- closed-list (genre, style) pair whose genre is one of the artist's
-- final genres.
select
    artist_id,
    'primary_style' as style_column,
    primary_style as attributed_style,
    primary_genre,
    secondary_genre
from {{ ref('int_artists_genre_attribution') }}
where primary_style is not null
  and not exists (
      select 1
      from {{ ref('discogs_genre_styles') }} d
      where d.discogs_style = primary_style
        and d.discogs_genre in (primary_genre, coalesce(secondary_genre, primary_genre))
  )

union all

select
    artist_id,
    'secondary_style',
    secondary_style,
    primary_genre,
    secondary_genre
from {{ ref('int_artists_genre_attribution') }}
where secondary_style is not null
  and not exists (
      select 1
      from {{ ref('discogs_genre_styles') }} d
      where d.discogs_style = secondary_style
        and d.discogs_genre in (primary_genre, coalesce(secondary_genre, primary_genre))
  )
