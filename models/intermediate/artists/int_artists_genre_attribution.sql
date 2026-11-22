/*

    Final genre / sous-genre attribution per artist.

    Grain: 1 row = 1 artist with at least one genre-classified tag.

    Scoring (weighted sum, explainable):

        method_weight  = manual / exact / alias 1.0, fuzzy 0.9, llm 0.8
                         (reliability of the mechanism)
        confidence     = tag-specificity weight from the seed, 1.0 by
                         default, lowered by seeds/tag_overrides.csv for
                         generic tags ("dance", "lo-fi", "oldies"...)
        row_weight     = method_weight x confidence x ln(1 + tag_count)
                         tag_count: source popularity weight, null -> 1
        genre_score = sum(row_weight) x (1 + 0.5 x (distinct_sources - 1))

    Selection:
        - primary_genre  = highest genre_score
          (ties: nb_sources desc, then genre name - deterministic)
        - secondary_genre = runner-up ONLY if
              nb_sources >= {{ var('attribution_min_secondary_sources', 2) }}
              and score_ratio >= {{ var('attribution_min_secondary_score_ratio', 0.5) }}
          otherwise null; the raw candidate + ratio + sources are kept
          for threshold analysis.
        - primary_style / secondary_style ranked among style rows whose
          genre is the final genre(s) - style is always coherent with the
          final genre. Style rule is ratio-only (styles are sparser).
        - is_ambiguous = runner-up ratio >=
          {{ var('attribution_ambiguity_ratio', 0.75) }} (top-2 nearly tied).

    Confidence:
        - primary_share = primary score / total score of the artist
        - combined_confidence = 0.6 x primary_share
                                + 0.4 x (nb_supporting_sources / 3)

*/

{% set min_secondary_ratio = var('attribution_min_secondary_score_ratio', 0.5) %}
{% set min_secondary_sources = var('attribution_min_secondary_sources', 2) %}
{% set min_secondary_style_ratio = var('attribution_min_secondary_style_ratio', 0.5) %}
{% set ambiguity_ratio = var('attribution_ambiguity_ratio', 0.75) %}

/*

    Row-level weights and per-genre scores are defined once in
    int_artists_tag_scores / int_artists_genre_scores and reused here -
    same values as the former in-line CTEs (guarded by
    test_attribution_scores_match_genre_scores), so the listening marts
    and this model always score identically.

*/

with tag_rows as (

    select
        artist_id,
        source,
        raw_tag,
        discogs_genre,
        discogs_style,
        tag_count,
        method_weight,
        confidence

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
        max(case when rank_position = 2 then discogs_genre end) as secondary_genre_candidate,
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
        secondary_genre_score / nullif(primary_genre_score, 0) as secondary_score_ratio_raw,
        primary_genre_score / nullif(total_score, 0) as primary_share_raw,

        case
            when secondary_genre_candidate is not null
                 and secondary_sources_count >= {{ min_secondary_sources }}
                 and secondary_genre_score / nullif(primary_genre_score, 0) >= {{ min_secondary_ratio }}
            then secondary_genre_candidate
        end as secondary_genre

    from genre_summary

),

/*

    Styles ranked only among rows whose genre is one of the final
    genre(s): the sous-genre is always coherent with the final genre.
*/
final_genres as (

    select
        artist_id,
        primary_genre,
        secondary_genre
    from genre_final

),

style_rows as (

    select
        t.artist_id,
        t.source,
        t.discogs_style,
        t.tag_count,
        t.method_weight,
        t.confidence
    from tag_rows t
    inner join final_genres g
        on t.artist_id = g.artist_id
       and t.discogs_genre in (g.primary_genre, g.secondary_genre)
    where t.discogs_style is not null

),

style_ranked as (

    select
        *,
        row_number() over (
            partition by artist_id
            order by
                style_score desc,
                nb_style_sources desc,
                discogs_style
        ) as rank_position
    from (
        select
            artist_id,
            discogs_style,
            sum(method_weight * confidence * ln(1 + coalesce(tag_count, 1)))
                * (1 + 0.5 * (count(distinct source) - 1)) as style_score,
            count(distinct source) as nb_style_sources
        from style_rows
        group by
            artist_id,
            discogs_style
    )

),

style_summary as (

    select
        artist_id,
        max(case when rank_position = 1 then discogs_style end) as primary_style,
        max(case when rank_position = 1 then style_score end) as primary_style_score,
        max(case when rank_position = 2 then discogs_style end) as secondary_style,
        max(case when rank_position = 2 then style_score end) as secondary_style_score
    from style_ranked
    group by artist_id

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

    g.primary_genre,

    round(g.primary_genre_score, 3) as primary_genre_score,
    round(g.primary_share_raw, 4) as primary_share,
    g.nb_supporting_sources,
    g.primary_nb_tags as nb_genre_tags,
    g.nb_distinct_genres,

    g.secondary_genre,

    g.secondary_genre_candidate,
    round(g.secondary_score_ratio_raw, 4) as secondary_score_ratio,
    g.secondary_sources_count,

    st.primary_style,
    round(st.primary_style_score, 3) as primary_style_score,

    st.secondary_style,
    round(
        st.secondary_style_score / nullif(st.primary_style_score, 0),
        4
    ) as secondary_style_score_ratio,

    round(
        0.6 * g.primary_share_raw + 0.4 * (g.nb_supporting_sources / 3.0),
        4
    ) as combined_confidence,

    coalesce(g.secondary_score_ratio_raw >= {{ ambiguity_ratio }}, false) as is_ambiguous

from genre_final g

left join style_summary st
    using (artist_id)

left join artist_names an
    using (artist_id)
