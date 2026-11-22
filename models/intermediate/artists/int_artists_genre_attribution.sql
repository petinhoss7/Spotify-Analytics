/*

    Final genre / sous-genre attribution per artist.

    Grain: 1 row = 1 artist with at least one genre-classified tag.

    The result is a *combination* of four attributes, so every artist is
    described by a primary and a secondary pair:

        primary_genre   + primary_style     (the strongest genre, and its
                                             strongest style for this artist)
        secondary_genre + secondary_style   (the runner-up genre, and ITS
                                             strongest style)

    Each style belongs to the genre it is paired with, so the combination
    always reads as two valid (genre, style) pairs - never a style from the
    primary genre sitting in the secondary slot.

    Scoring (weighted sum, explainable):

        row_weight  = method_weight x ln(1 + tag_count)
                      method_weight: verified/exact/alias 1.0, fuzzy 0.9, llm 0.8
                      tag_count: source popularity weight, null -> 1
        genre_score = sum(row_weight) x (1 + 0.5 x (distinct_sources - 1))

    Selection:
        - primary_genre = highest genre_score
          (ties: nb_sources desc, then genre name - deterministic)
        - secondary_genre = runner-up genre, filled whenever the artist has a
          second scored genre. It is NOT gated: an artist with two genres has
          two genres, and hiding the weaker one would leave the combination
          incomplete. Its strength is reported instead, through
          secondary_score_ratio and secondary_sources_count.
        - primary_style = highest scoring style among the primary genre's rows
        - secondary_style = highest scoring style among the secondary genre's
          rows (null when the artist has no secondary genre, or no styled tag
          under it)
        - is_ambiguous = runner-up ratio >=
          {{ var('attribution_ambiguity_ratio', 0.75) }} (top-2 nearly tied,
          so treat primary and secondary as an unordered pair)

    Confidence:
        - primary_share = primary score / total score of the artist
        - combined_confidence = 0.6 x primary_share
                                + 0.4 x (nb_supporting_sources / 3)

*/

{% set ambiguity_ratio = var('attribution_ambiguity_ratio', 0.75) %}

/*
    Row-level weights and per-genre scores are defined once in
    int_artists_tag_scores / int_artists_genre_scores and reused here, so the
    listening marts and this model can never score differently (guarded by
    test_attribution_scores_match_genre_scores).
*/

with tag_rows as (

    select
        artist_id,
        source,
        raw_tag,
        discogs_genre,
        discogs_style,
        tag_count,
        method_weight

    from {{ ref('int_artists_tag_scores') }}

),

genre_scores as (

    select
        artist_id,
        discogs_genre,
        genre_score,
        nb_sources,
        nb_tags

    from {{ ref('int_artists_genre_scores') }}

),

genre_ranked as (

    select
        *,
        row_number() over (
            partition by artist_id
            order by
                genre_score desc,
                nb_sources desc,
                discogs_genre
        ) as rank_position
    from genre_scores

),

genre_summary as (

    select
        artist_id,
        max(case when rank_position = 1 then discogs_genre end) as primary_genre,
        max(case when rank_position = 1 then genre_score end) as primary_genre_score,
        max(case when rank_position = 1 then nb_sources end) as nb_supporting_sources,
        max(case when rank_position = 1 then nb_tags end) as primary_nb_tags,
        max(case when rank_position = 2 then discogs_genre end) as secondary_genre,
        max(case when rank_position = 2 then genre_score end) as secondary_genre_score,
        max(case when rank_position = 2 then nb_sources end) as secondary_sources_count,
        count(*) as nb_distinct_genres,
        sum(genre_score) as total_score
    from genre_ranked
    group by artist_id

),

genre_final as (

    select
        *,
        secondary_genre_score / nullif(primary_genre_score, 0) as secondary_score_ratio,
        primary_genre_score / nullif(total_score, 0) as primary_share

    from genre_summary

),

/*
    Style scores, then ranked *within each genre*, so the primary and the
    secondary slot each get the best style of their own genre.
*/
style_scores as (

    select
        artist_id,
        discogs_genre,
        discogs_style,
        sum(method_weight * ln(1 + coalesce(tag_count, 1)))
            * (1 + 0.5 * (count(distinct source) - 1)) as style_score,
        count(distinct source) as nb_style_sources
    from tag_rows
    where discogs_style is not null
    group by
        artist_id,
        discogs_genre,
        discogs_style

),

style_ranked as (

    select
        *,
        row_number() over (
            partition by artist_id, discogs_genre
            order by
                style_score desc,
                nb_style_sources desc,
                discogs_style
        ) as style_rank
    from style_scores

),

artist_names as (

    select
        artist_id,
        min(spotify_artist_name) as spotify_artist_name
    from {{ ref('int_source_tag_classification') }}
    group by artist_id

)

select

    g.artist_id,

    an.spotify_artist_name,

    -- primary pair
    g.primary_genre,

    round(g.primary_genre_score, 3) as primary_genre_score,
    round(g.primary_share, 4) as primary_share,
    g.nb_supporting_sources,
    g.primary_nb_tags as nb_genre_tags,
    g.nb_distinct_genres,

    ps.discogs_style as primary_style,
    round(ps.style_score, 3) as primary_style_score,

    -- secondary pair (null when the artist has a single scored genre, or no
    -- styled tag under the runner-up genre)
    g.secondary_genre,

    round(g.secondary_genre_score, 3) as secondary_genre_score,
    round(g.secondary_score_ratio, 4) as secondary_score_ratio,
    g.secondary_sources_count,

    ss.discogs_style as secondary_style,
    round(ss.style_score, 3) as secondary_style_score,

    round(
        0.6 * g.primary_share + 0.4 * (g.nb_supporting_sources / 3.0),
        4
    ) as combined_confidence,

    coalesce(g.secondary_score_ratio >= {{ ambiguity_ratio }}, false) as is_ambiguous

from genre_final g

left join style_ranked ps
    on ps.artist_id = g.artist_id
   and ps.discogs_genre = g.primary_genre
   and ps.style_rank = 1

left join style_ranked ss
    on ss.artist_id = g.artist_id
   and ss.discogs_genre = g.secondary_genre
   and ss.style_rank = 1

left join artist_names an
    on an.artist_id = g.artist_id
