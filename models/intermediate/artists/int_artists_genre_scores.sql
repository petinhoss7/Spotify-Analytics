/*

    Genre-level evidence scores per artist.

    Grain: 1 row = 1 artist x 1 Discogs genre (every scored genre,
    not only the sanctioned primary/secondary pair).

    genre_score = sum(row_weight) x (1 + 0.5 x (distinct_sources - 1))
        row_weight comes from int_artists_tag_scores.

    genre_share = genre_score / total score of the artist (0 to 1,
    shares sum to 1 per artist). This is the evidence-proportional
    weight consumed by fct_genre_listening: each artist's listening
    time is distributed across ALL their scored genres proportionally
    to genre_share, not only the primary/secondary attribution pair.

    Full float precision is kept on purpose (no rounding): the
    attribution model reuses these values, and rounding here would
    drift its outputs.

*/

with genre_scores as (

    select
        artist_id,
        discogs_genre,
        sum(row_weight) as raw_weight,
        count(distinct source) as nb_sources,
        count(distinct raw_tag) as nb_tags,
        sum(row_weight)
            * (1 + 0.5 * (count(distinct source) - 1)) as genre_score

    from {{ ref('int_artists_tag_scores') }}
    group by
        artist_id,
        discogs_genre

),

totals as (

    select
        artist_id,
        sum(genre_score) as total_score

    from genre_scores
    group by artist_id

)

select

    g.artist_id,
    g.discogs_genre,

    g.raw_weight,
    g.nb_sources,
    g.nb_tags,
    g.genre_score,

    t.total_score,

    g.genre_score / t.total_score as genre_share

from genre_scores g

join totals t
    using (artist_id)
