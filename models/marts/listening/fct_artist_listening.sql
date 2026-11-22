/*

    Artist listening rollup: listening time per artist per calendar month.

    Grain: 1 row = 1 listening month x 1 artist.

    A stream's minutes are divided by the number of artists on the track
    (int_stream_artists), so a collaboration credits each of its artists a
    share instead of crediting the whole track to one of them. Every artist
    of the bridge is present, including those without a genre attribution -
    their minutes stay, with null genre columns.

    The genre columns are the *combination* built by
    int_artists_genre_attribution (primary + secondary pair), denormalized
    here because this is the table you filter on, and a hand-made artist
    override is reflected as is (attribution_source = 'manual', with
    override_reason).

    Reconciliation: per month, sum(total_minutes) equals the month's minutes
    minus the streams whose track is absent from the bridge (guarded by
    test_fct_artist_listening_reconciles). Those streams have no artist to
    credit, which is why this table cannot hold a month's grand total on its
    own - fct_genre_listening carries them in its 'no_artist_data' bucket.

    Reading: this is a MEASURE (time per artist), not the artist's genre
    label. The label is on the same row, but it is a description.

*/

with artists as (

    select
        date_trunc('month', stream_date) as listening_month,
        artist_id,
        sum(artist_minutes) as total_minutes,
        sum(artist_stream_fraction) as fractional_stream_count,
        count(distinct track_id) as nb_tracks,
        count(distinct stream_id) as nb_streams

    from {{ ref('int_stream_artists') }}

    group by
        date_trunc('month', stream_date),
        artist_id

),

month_totals as (

    select
        listening_month,
        sum(total_minutes) as month_minutes

    from artists
    group by listening_month

)

select

    a.listening_month,
    a.artist_id,

    i.spotify_artist_name as artist_name,

    -- the artist's combination, denormalized for filtering
    i.primary_genre,
    i.primary_style,
    i.secondary_genre,
    i.secondary_style,
    i.nb_supporting_sources,
    t.attribution_source,
    t.override_reason,

    round(a.total_minutes, 6) as total_minutes,
    round(a.fractional_stream_count, 6) as fractional_stream_count,
    a.nb_tracks,
    a.nb_streams,

    round(
        a.total_minutes / nullif(m.month_minutes, 0),
        6
    ) as share_of_artist_minutes_in_month

from artists a

left join {{ ref('int_artists') }} i
    on i.artist_id = a.artist_id

left join {{ ref('int_artists_genre_attribution') }} t
    on t.artist_id = a.artist_id

left join month_totals m
    on m.listening_month = a.listening_month
