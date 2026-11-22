-- Roll-up: the styles of a genre must sum exactly to that genre's minutes in
-- fct_genre_listening. Both marts group the same allocation
-- (int_stream_artist_pairs), so any difference means the two marts have
-- drifted apart and that "the styles of Electronic" no longer describes the
-- same listening time as "Electronic".
with from_styles as (

    select
        listening_month,
        discogs_genre,
        sum(total_minutes) as style_minutes
    from {{ ref('fct_style_listening') }}
    group by
        listening_month,
        discogs_genre

),

from_genres as (

    select
        listening_month,
        discogs_genre,
        total_minutes as genre_minutes
    from {{ ref('fct_genre_listening') }}

)

select
    coalesce(s.listening_month, g.listening_month) as listening_month,
    coalesce(s.discogs_genre, g.discogs_genre) as discogs_genre,
    s.style_minutes,
    g.genre_minutes
from from_styles s

full outer join from_genres g
    on s.listening_month = g.listening_month
   and s.discogs_genre = g.discogs_genre

where s.listening_month is null
   or g.listening_month is null
   or abs(s.style_minutes - g.genre_minutes) > 0.01
