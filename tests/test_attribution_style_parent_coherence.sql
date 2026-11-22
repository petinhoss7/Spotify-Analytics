-- Each attributed style must be a valid closed-list (genre, style) pair, and
-- its parent genre must be the one it is paired with: the primary style must
-- live under the primary genre, and the secondary style under the secondary
-- genre. This is what makes the attribution a coherent combination of two
-- (genre, style) pairs rather than four independent slots.
select
    a.artist_id,
    'primary_style' as style_column,
    a.primary_style as attributed_style,
    a.primary_genre as parent_genre
from {{ ref('int_artists_genre_attribution') }} a
where a.primary_style is not null
  and not exists (
      select 1
      from {{ ref('discogs_genre_styles') }} d
      where d.discogs_genre = a.primary_genre
        and d.discogs_style = a.primary_style
  )

union all

select
    a.artist_id,
    'secondary_style',
    a.secondary_style,
    a.secondary_genre
from {{ ref('int_artists_genre_attribution') }} a
where a.secondary_style is not null
  and not exists (
      select 1
      from {{ ref('discogs_genre_styles') }} d
      where d.discogs_genre = a.secondary_genre
        and d.discogs_style = a.secondary_style
  )
