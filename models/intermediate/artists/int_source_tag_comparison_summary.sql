/*

    Per-source classification summary.

    Grain: 1 row = 1 source (lastfm, musicbrainz, rapidapi).

    Coverage and quality figures for the line-by-line model
    int_source_tag_classification, at both taxonomy levels
    (genre and style / sous-genre), plus the populations excluded
    from the cross-source comparison.

*/

with per_source as (

    select
        source,
        count(*) as tag_rows,
        count(distinct raw_tag) as distinct_tags,
        count(distinct artist_id) as distinct_artists,

        count(*) filter (where classification_status = 'genre') as genre_rows,
        count(*) filter (where classification_status = 'non_genre') as non_genre_rows,
        count(*) filter (where classification_status = 'empty_tag') as empty_tag_rows,
        count(*) filter (where classification_status = 'unmapped') as unmapped_rows,

        count(*) filter (where classification_status = 'genre'
                          and discogs_style is not null) as style_rows,

        count(*) filter (where match_method = 'verified') as method_verified,
        count(*) filter (where match_method = 'exact') as method_exact,
        count(*) filter (where match_method = 'alias') as method_alias,
        count(*) filter (where match_method = 'fuzzy') as method_fuzzy,
        count(*) filter (where match_method = 'llm') as method_llm,
        count(*) filter (where match_method = 'noise') as method_noise

    from {{ ref('int_source_tag_classification') }}
    group by source

),

/*

    Artists genre-classified by exactly one source: present in the
    line-by-line model but excluded from int_source_tag_cross_comparison.
    Artists with no genre at all from any source are not counted here
    (nothing to compare).
*/
single_source_artists as (

    select
        c.source,
        count(distinct c.artist_id) as excluded_single_source_artists
    from {{ ref('int_source_tag_classification') }} c
    where c.classification_status = 'genre'
      and c.artist_id in (
          select artist_id
          from (
              select
                  artist_id,
                  count(distinct source) as nb_sources
              from {{ ref('int_source_tag_classification') }}
              where classification_status = 'genre'
              group by artist_id
          )
          where nb_sources = 1
      )
    group by c.source

),

/*

    Artists with styles from >= 2 sources: the population actually
    scored on the style level. Artists with styles from exactly one
    source are excluded from style scoring (subgenre_agreement_score
    is null for them) and counted here per source of those styles.
*/
style_source_counts as (

    select
        artist_id,
        count(distinct source) as nb_style_sources
    from {{ ref('int_source_tag_classification') }}
    where classification_status = 'genre'
      and discogs_style is not null
    group by artist_id

),

multi_style_artists as (

    select artist_id
    from style_source_counts
    where nb_style_sources >= 2

),

single_style_source_artists as (

    select
        c.source,
        count(distinct c.artist_id) as excluded_single_style_source_artists
    from {{ ref('int_source_tag_classification') }} c
    where c.classification_status = 'genre'
      and c.discogs_style is not null
      and c.artist_id not in (select artist_id from multi_style_artists)
    group by c.source

)

select

    ps.source,

    ps.tag_rows,
    ps.distinct_tags,
    ps.distinct_artists,

    ps.genre_rows,
    ps.non_genre_rows,
    ps.empty_tag_rows,
    ps.unmapped_rows,

    round(ps.genre_rows / nullif(ps.tag_rows, 0), 4) as genre_rate,

    ps.style_rows,
    round(ps.style_rows / nullif(ps.genre_rows, 0), 4) as style_rate,

    ps.method_verified,
    ps.method_exact,
    ps.method_alias,
    ps.method_fuzzy,
    ps.method_llm,
    ps.method_noise,

    coalesce(ss.excluded_single_source_artists, 0) as excluded_single_source_artists,

    coalesce(sss.excluded_single_style_source_artists, 0) as excluded_single_style_source_artists

from per_source ps

left join single_source_artists ss
    using (source)

left join single_style_source_artists sss
    using (source)
