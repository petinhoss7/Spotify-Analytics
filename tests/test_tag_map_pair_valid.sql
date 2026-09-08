-- Every (genre, style) pair in the tag map must be a valid pair of the
-- closed Discogs list. Genre-only rows (null style) are valid by design.
select
    m.raw_tag,
    m.discogs_genre,
    m.discogs_style
from {{ ref('tag_genre_map') }} m
left join {{ ref('discogs_genre_styles') }} d
    on m.discogs_genre = d.discogs_genre
   and m.discogs_style is not distinct from d.discogs_style
where m.is_genre_tag
  and d.discogs_genre is null
