with source as (

    select
        artist_id,
        artist_name,
        genres

    from {{ ref('stg_spotify_artists') }}

),

genres as (

    select
        artist_id,
        artist_name,
        trim(genre) as genre

    from source,
         unnest(from_json(genres, '["VARCHAR"]')) as t(genre)

)

select distinct
    artist_id,
    artist_name,
    genre as tag_name

from genres

where genre is not null
  and trim(genre) != ''