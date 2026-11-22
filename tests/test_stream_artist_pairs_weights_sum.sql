-- The allocation must be complete for every artist it covers: for a given
-- stream and artist, the pair weights must sum to 1 / artist_count. It cannot
-- be 1 per stream as a whole, because an artist of the bridge without a genre
-- attribution contributes no pair row at all - their share is exactly what
-- the 'unclassified' bucket of the marts carries. Without this, the listening
-- marts would either lose or double-count time.
select
    stream_id,
    artist_id,
    artist_count,
    sum(pair_weight) as total_weight
from {{ ref('int_stream_artist_pairs') }}
group by
    stream_id,
    artist_id,
    artist_count
having abs(sum(pair_weight) - 1.0 / artist_count) > 0.000001
