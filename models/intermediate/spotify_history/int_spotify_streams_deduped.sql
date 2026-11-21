with ranked_rows as (

    select
        *,
        row_number() over (
            partition by stream_id
            order by loaded_at desc
        ) as dedup_rank
    from {{ ref('stg_spotify_history') }}

)

select * exclude (dedup_rank)
from ranked_rows
where dedup_rank = 1
