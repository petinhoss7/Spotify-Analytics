with source as (

    select *
    from {{ source('rapidapi', 'RAW_SPOTIFY_TRACK_ARTISTS') }}

),

renamed as (

    select

        nullif(trim(track_id), '')::varchar           as track_id,
        nullif(trim(artist_id), '')::varchar          as artist_id,
        nullif(trim(artist_name), '')::varchar        as artist_name,

        loaded_at::TIMESTAMP                         as loaded_at

    from source

)

select *
from renamed