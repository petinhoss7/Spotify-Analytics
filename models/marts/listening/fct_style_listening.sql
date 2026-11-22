/*

    Style (sous-genre) listening rollup: listening time attributed to Discogs
    styles per calendar month.

    Grain: 1 row = 1 listening month x 1 genre x 1 style.

    Same allocation as fct_genre_listening, but grouped by style instead of
    genre - both read int_stream_artist_pairs, the single definition. The
    genre is kept in the grain because a style name can live under several
    genres ("Dub" is both Electronic and Reggae) and because it makes the
    roll-up exact: for every month, the styles of a genre sum to that genre's
    minutes in fct_genre_listening (guarded by
    test_fct_style_listening_rolls_up_to_genre).

    Buckets, so that a month's total still equals the month's listening
    minutes (guarded by test_fct_style_listening_reconciles):

        - '(no_style)'     : the pair has a genre but no specific style, or
                             the artist has no styled tag under it
        - 'unclassified'   : artist known via the bridge but with no genre
                             attribution
        - 'no_artist_data' : track absent from the track-artist bridge

    Evidence caveat, on purpose: the style level is sparse - 65.7% of
    (artist, style) couples rest on a single tag - so style figures are
    inherently thinner than genre figures. Per-artist evidence is in
    int_artists_tag_scores; nb_artists here says how widely a style is shared
    across the artists actually listened to.

*/

with attributed as (

    select
        date_trunc('month', stream_date) as listening_month,
        discogs_genre,
        coalesce(discogs_style, '(no_style)') as discogs_style,
        sum(allocated_minutes) as style_minutes,
        sum(pair_weight) as style_streams,
        count(distinct artist_id) as nb_artists

    from {{ ref('int_stream_artist_pairs') }}

    group by
        date_trunc('month', stream_date),
        discogs_genre,
        coalesce(discogs_style, '(no_style)')

),

unclassified as (

    select
        date_trunc('month', f.stream_date) as listening_month,
        'unclassified' as discogs_genre,
        'unclassified' as discogs_style,
        sum(f.minutes_played / b.artist_count) as style_minutes,
        sum(1.0 / b.artist_count) as style_streams,
        count(distinct b.artist_id) as nb_artists

    from {{ ref('fct_streams') }} f

    inner join {{ ref('int_tracks_artists') }} b
        on f.track_id = b.track_id

    left join {{ ref('int_artists_genre_attribution') }} a
        on a.artist_id = b.artist_id

    where a.artist_id is null

    group by date_trunc('month', f.stream_date)

),

no_artist_data as (

    select
        date_trunc('month', f.stream_date) as listening_month,
        'no_artist_data' as discogs_genre,
        'no_artist_data' as discogs_style,
        sum(f.minutes_played) as style_minutes,
        count(*) as style_streams,
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
    discogs_style,

    round(style_minutes, 6) as total_minutes,
    round(style_streams, 6) as fractional_stream_count,
    nb_artists,

    round(
        style_minutes
        / nullif(sum(style_minutes) over (partition by listening_month), 0),
        6
    ) as share_of_month_minutes

from all_buckets
