with source as (

    select *
    from {{ source('rapidapi', 'RAW_SPOTIFY_ARTISTS') }}

),

renamed as (

    select

        nullif(trim(artist_id), '')::varchar              as artist_id,
        nullif(trim(artist_name), '')::varchar            as artist_name,

        popularity::integer                               as popularity,
        followers_total::integer                                as followers,

        genres,
        nullif(trim(artist_uri), '')::varchar             as artist_uri,

        loaded_at::TIMESTAMP                         as loaded_at

    from source

)

select *
from renamed