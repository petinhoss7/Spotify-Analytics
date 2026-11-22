/*

    Genre listening rollup: listening time attributed to Discogs genres per
    calendar month.

    Grain: 1 row = 1 listening month x 1 genre (the 15 closed Discogs genres
    + 2 explicit reconciliation buckets).

    Attribution comes from int_stream_artist_pairs, the single definition of
    the allocation:

        1. each stream's minutes are divided by the number of artists on the
           track
        2. each artist's share goes to their primary pair (0.7) and to their
           secondary pair (0.3) when they have one - an artist without a
           secondary keeps the whole share on the primary pair

    The pair is (genre, style), so this model is simply that allocation
    grouped by genre; fct_style_listening is the same allocation grouped by
    style, and the styles of a genre roll up exactly to this table (guarded by
    test_fct_style_listening_rolls_up_to_genre).

    Reconciliation: for every month, sum(total_minutes) equals the month's
    music listening minutes (guarded by
    test_fct_genre_listening_reconciles). Two buckets absorb the
    non-attributable remainder:

        - 'unclassified'   : artist known via the bridge but with no genre
                             attribution (no primary pair)
        - 'no_artist_data' : track absent from the track-artist bridge

    fractional_stream_count is the stream count with the same split rules
    (sum of 1/artist_count x pair weight); its monthly total equals the
    fractionally-deduplicated stream count. In the 'no_artist_data' bucket it
    is a plain stream count (no artist to split across).

    Note: this is a MEASURE, not a track label. It answers "how much time in
    each genre", not "which genre is this track" - that is
    fct_streams.lead_primary_genre, a denomination. Summing minutes by that
    column gives different numbers on purpose (it cannot spread the 13% of
    minutes whose track artists disagree on genre).

*/

with attributed as (

    select
        date_trunc('month', stream_date) as listening_month,
        discogs_genre,
        sum(allocated_minutes) as genre_minutes,
        sum(pair_weight) as genre_streams,
        count(distinct artist_id) as nb_artists

    from {{ ref('int_stream_artist_pairs') }}

    group by
        date_trunc('month', stream_date),
        discogs_genre

),

/*
    Artists mapped in the bridge but with no genre attribution at all: their
    fractional minutes stay, labelled explicitly.
*/
unclassified as (

    select
        date_trunc('month', f.stream_date) as listening_month,
        'unclassified' as discogs_genre,
        sum(f.minutes_played / b.artist_count) as genre_minutes,
        sum(1.0 / b.artist_count) as genre_streams,
        count(distinct b.artist_id) as nb_artists

    from {{ ref('fct_streams') }} f

    inner join {{ ref('int_tracks_artists') }} b
        on f.track_id = b.track_id

    left join {{ ref('int_artists_genre_attribution') }} a
        on a.artist_id = b.artist_id

    where a.artist_id is null

    group by date_trunc('month', f.stream_date)

),

/*
    Streams whose track is absent from the track-artist bridge: no artist,
    hence no genre can be derived.
*/
no_artist_data as (

    select
        date_trunc('month', f.stream_date) as listening_month,
        'no_artist_data' as discogs_genre,
        sum(f.minutes_played) as genre_minutes,
        count(*) as genre_streams,
        cast(null as bigint) as nb_artists

    from {{ ref('fct_streams') }} f

    left join {{ ref('int_tracks_artists') }} b
        on f.track_id = b.track_id

    where b.track_id is null

    group by date_trunc('month', f.stream_date)

),

all_buckets as (

    select * from attributed
    union all
    select * from unclassified
    union all
    select * from no_artist_data

)

select

    listening_month,
    discogs_genre,

    round(genre_minutes, 6) as total_minutes,
    round(genre_streams, 6) as fractional_stream_count,
    nb_artists,

    round(
        genre_minutes
        / nullif(sum(genre_minutes) over (partition by listening_month), 0),
        6
    ) as share_of_month_minutes

from all_buckets
