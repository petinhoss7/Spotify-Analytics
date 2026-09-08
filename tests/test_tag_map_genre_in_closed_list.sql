-- Every genre in the tag map must exist in the closed Discogs list.
select
    m.raw_tag,
    m.discogs_genre
from {{ ref('tag_genre_map') }} m
where m.is_genre_tag
  and m.discogs_genre not in (
      select distinct discogs_genre
      from {{ ref('discogs_genre_styles') }}
  )
