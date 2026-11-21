/*

    Genre listening rollup: listening time attributed to Discogs
    genres per calendar month.

    Grain: 1 row = 1 listening month x 1 genre (the 15 closed Discogs
    genres + 2 explicit reconciliation buckets).

    Attribution scheme (evidence-proportional, over ALL scored genres):

        1. each stream's minutes are split fractionally across the
           track's artists (minutes / artist_count)
        2. each artist's fractional minutes are distributed across ALL
           their scored genres proportionally to
           int_artists_genre_scores.genre_share

    This keeps the genre ranking per artist faithful to the tag
    evidence (no gate-induced rank flips) and names every genre that
    carries evidence - no opaque "other" bucket.

    Reconciliation: for every month, sum(total_minutes) equals the
    month's music listening minutes (guarded by
    test_fct_genre_listening_reconciles). Two buckets absorb the
    non-attributable remainder:

        - 'unclassified'   : artist known via the bridge but with no
                             genre evidence (no genre-classified tag)
        - 'no_artist_data' : track absent from the track-artist bridge

    fractional_stream_count is the stream count with the same split
    rules (sum 1/artist_count per stream, distributed by genre_share);
    its monthly total equals the fractionally-deduplicated stream
    count. In the 'no_artist_data' bucket it is a plain stream count
    (no artist to split across).

*/

with stream_artist_minutes as (

    select
        date_trunc('month', f.stream_date) as listening_month,
        b.artist_id,
        f.minutes_played / b.artist_count as artist_minutes,
        1.0 / b.artist_count as artist_stream_fraction

    from {{ ref('fct_streams') }} f

    join {{ ref('int_tracks_artists') }} b
        on f.track_id = b.track_id

),

attributed as (

    select
        sam.listening_month,
        gs.discogs_genre,
        sum(sam.artist_minutes * gs.genre_share) as genre_minutes,
        sum(sam.artist_stream_fraction * gs.genre_share) as genre_streams,
        count(distinct sam.artist_id) as nb_artists

    from stream_artist_minutes sam

    join {{ ref('int_artists_genre_scores') }} gs
        using (artist_id)

    group by
        sam.listening_month,
        gs.discogs_genre

),

/*

    Mapped artists with no genre evidence at all: their fractional
    minutes stay, labelled explicitly.
*/
unclassified as (

    select
        sam.listening_month,
        'unclassified' as discogs_genre,
        sum(sam.artist_minutes) as genre_minutes,
        sum(sam.artist_stream_fraction) as genre_streams,
        count(distinct sam.artist_id) as nb_artists

    from stream_artist_minutes sam

    left join {{ ref('int_artists_genre_scores') }} gs
        using (artist_id)

    where gs.artist_id is null
    group by
        sam.listening_month,
        gs.discogs_genre

),

/*

    Streams whose track is absent from the track-artist bridge: no
    artist (hence no genre) can be derived.
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
    group by
        date_trunc('month', f.stream_date),
        'no_artist_data'

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
