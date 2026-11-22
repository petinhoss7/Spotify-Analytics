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
        - secondary_genre = runner-up genre, kept when it is real evidence:
              nb_tags >= {{ var('attribution_min_secondary_tags', 2) }}
              or score_ratio >= {{ var('attribution_min_secondary_score_ratio', 0.10) }}
          A genre resting on a single stray tag is not a genre (an isolated
          "pop" or "orchestral" tag used to create a second genre at ~1% of
          the primary score). Counts, not weights, are used for the tag
          floor: sources without a tag count weigh less by construction, and
          a weight floor would disqualify Spotify genres. Below the floor the
          secondary pair is null; strength is still reported through
          secondary_score_ratio, secondary_nb_tags and secondary_sources_count.
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

{% set min_secondary_tags = var('attribution_min_secondary_tags', 2) %}
{% set min_secondary_ratio = var('attribution_min_secondary_score_ratio', 0.10) %}
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
        max(case when rank_position = 2 then discogs_genre end) as secondary_genre_candidate,
        max(case when rank_position = 2 then genre_score end) as secondary_genre_score,
        max(case when rank_position = 2 then nb_sources end) as secondary_sources_count,
        max(case when rank_position = 2 then nb_tags end) as secondary_nb_tags,
        count(*) as nb_distinct_genres,
        sum(genre_score) as total_score
    from genre_ranked
    group by artist_id

),

genre_final as (

    select
        *,
        secondary_genre_score / nullif(primary_genre_score, 0) as secondary_score_ratio,
        primary_genre_score / nullif(total_score, 0) as primary_share,

        -- a genre resting on a single stray tag is not a genre: keep the
        -- runner-up only when it has real evidence behind it
        case
            when secondary_genre_candidate is not null
                 and (
                     secondary_nb_tags >= {{ min_secondary_tags }}
                     or secondary_genre_score / nullif(primary_genre_score, 0)
                        >= {{ min_secondary_ratio }}
                 )
            then secondary_genre_candidate
        end as secondary_genre

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

),

/*
    Hand-made artist-level corrections. The model decides from tag evidence,
    which cannot judge plausibility - it cannot know that "black metal" is
    absurd for a house producer while the ratio and tag counts look exactly
    like a legitimate secondary. Such cases are recorded here by hand, with a
    reason, and this overrides the four label columns for the listed artists
    only. Everything the evidence produced (scores, share, ratio, confidence)
    is nulled for them rather than left describing a ranking that no longer
    applies, and attribution_source says where the labels come from.
*/
manual_overrides as (

    select
        artist_id,
        primary_genre,
        nullif(primary_style, '') as primary_style,
        nullif(secondary_genre, '') as secondary_genre,
        nullif(secondary_style, '') as secondary_style,
        comment
    from {{ ref('artist_overrides') }}

)

select

    g.artist_id,

    an.spotify_artist_name,

    -- primary pair
    coalesce(o.primary_genre, g.primary_genre) as primary_genre,

    case when o.artist_id is null then round(g.primary_genre_score, 3) end as primary_genre_score,
    case when o.artist_id is null then round(g.primary_share, 4) end as primary_share,
    g.nb_supporting_sources,
    g.primary_nb_tags as nb_genre_tags,
    g.nb_distinct_genres,

    case when o.artist_id is null then ps.discogs_style else o.primary_style end as primary_style,
    case when o.artist_id is null then round(ps.style_score, 3) end as primary_style_score,

    -- secondary pair (empty in the seed means "explicitly none")
    case when o.artist_id is not null then o.secondary_genre else g.secondary_genre end as secondary_genre,

    case when o.artist_id is null then round(g.secondary_genre_score, 3) end as secondary_genre_score,
    case when o.artist_id is null then round(g.secondary_score_ratio, 4) end as secondary_score_ratio,
    case when o.artist_id is null then g.secondary_sources_count end as secondary_sources_count,
    case when o.artist_id is null then g.secondary_nb_tags end as secondary_nb_tags,

    case when o.artist_id is not null then o.secondary_style else ss.discogs_style end as secondary_style,
    case when o.artist_id is null then round(ss.style_score, 3) end as secondary_style_score,

    case
        when o.artist_id is null then round(
            0.6 * g.primary_share + 0.4 * (g.nb_supporting_sources / 3.0), 4
        )
    end as combined_confidence,

    case
        when o.artist_id is null
        then coalesce(g.secondary_score_ratio >= {{ ambiguity_ratio }}, false)
        else false
    end as is_ambiguous,

    case when o.artist_id is null then 'evidence' else 'manual' end as attribution_source,
    o.comment as override_reason

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

left join manual_overrides o
    on o.artist_id = g.artist_id
