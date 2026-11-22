-- Every manual artist override must be usable: its primary genre and every
-- style it names must exist in the closed taxonomy, the primary style must
-- belong to the primary genre, and the secondary style (when given) to the
-- secondary genre. A typo here would silently put an unknown genre into the
-- artist dimension.
select
    o.artist_id,
    o.artist_name,
    o.primary_genre,
    o.primary_style,
    o.secondary_genre,
    o.secondary_style
from {{ ref('artist_overrides') }} o
where o.primary_genre not in (select distinct discogs_genre from {{ ref('discogs_genre_styles') }})
   or not exists (
        select 1 from {{ ref('discogs_genre_styles') }} d
        where d.discogs_genre = o.primary_genre
          and d.discogs_style = nullif(o.primary_style, '')
   )
   or (
        nullif(o.secondary_style, '') is not null
        and not exists (
            select 1 from {{ ref('discogs_genre_styles') }} d
            where d.discogs_genre = nullif(o.secondary_genre, '')
              and d.discogs_style = nullif(o.secondary_style, '')
        )
   )
   or (
        nullif(o.secondary_genre, '') is not null
        and o.secondary_genre not in (select distinct discogs_genre from {{ ref('discogs_genre_styles') }})
   )
