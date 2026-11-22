/*

    Allocation of a stream's listening time over the (genre, style) pairs of
    the artists on the track - the single definition of "which genre does this
    listening belong to", consumed by every listening mart.

    Grain: 1 row = 1 stream x 1 artist x 1pair (genre, style).

    Rule:

        for each artist on the track:
            share = minutes_played / artist_count
            (primary_genre, primary_style)     <- share x 0.7
            (secondary_genre, secondary_style) <- share x 0.3   if it exists
            otherwise the primary pair keeps the whole share

        pair_weight = (1 / artist_count) x (0.7 or 0.3)

    Invariant: the pair_weight of the rows of one stream sums to 1, so the
    sum of allocated_minutes over all rows equals the stream's minutes.
    Guarded by test_stream_artist_pairs_weights_sum.

    Why a proportion at all: the genre is an attribute of the ARTIST (a fact,
    never divided), while listening time is a quantity. When one quantity has
    to be filed under several genres, dividing it is what keeps the total
    additive instead of double-counting the same minute.

    The primary pair is never null, so every artist in the bridge contributes
    at least one row. A pair whose style is null is kept as is: each mart
    decides its own bucket for it (fct_style_listening uses '(no_style)').

    Weights are vars (attribution_primary_pair_weight / _secondary_pair_weight)
    and must sum to 1.

*/

with artists as (

    select
        stream_id,
        stream_date,
        track_id,
        artist_id,
        artist_count,
        artist_minutes,
        artist_stream_fraction

    from {{ ref('int_stream_artists') }}

),

pairs as (

    select
        artist_id,
        primary_genre as discogs_genre,
        primary_style as discogs_style,
        'primary' as pair_rank,
        case
            when secondary_genre is null then 1.0
            else {{ var('attribution_primary_pair_weight', 0.7) }}
        end as pair_weight

    from {{ ref('int_artists_genre_attribution') }}

    union all

    select
        artist_id,
        secondary_genre,
        secondary_style,
        'secondary',
        {{ var('attribution_secondary_pair_weight', 0.3) }}

    from {{ ref('int_artists_genre_attribution') }}
    where secondary_genre is not null

)

select

    a.stream_id,
    a.stream_date,
    a.track_id,

    a.artist_id,
    a.artist_count,

    p.pair_rank,
    p.discogs_genre,
    p.discogs_style,

    a.artist_stream_fraction * p.pair_weight as pair_weight,
    a.artist_minutes * p.pair_weight as allocated_minutes

from artists a

inner join pairs p
    on p.artist_id = a.artist_id
