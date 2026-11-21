/*

    Cross-source genre AND style agreement at artist level.

    Grain: 1 row = 1 artist genre-classified by at least 2 sources.

    For each artist, the Discogs genre and style sets derived from each
    source independently are compared against the others:

        Genre level:
        - genres_lastfm / genres_musicbrainz / genres_rapidapi : pivoted sets
        - shared_genres : genres identified by >= 2 sources
        - union_genres  : all genres identified across sources
        - agreement_score = |shared| / |union|  (simple Jaccard, 0 to 1)

        Style level (sous-genres):
        - styles_lastfm / styles_musicbrainz / styles_rapidapi : pivoted sets
        - shared_styles / union_styles + subgenre_agreement_score
        - Matching is style-name-only: two sources agree on "Ska" even if
          one places it under Reggae and the other under Rock; genre-level
          agreement is measured separately above.
        - null when the artist has styles from fewer than 2 sources
          (styles are sparser than genres by design).

    Artists with genres from a single source are excluded by design
    (no comparison possible); they are counted in
    int_source_tag_comparison_summary.excluded_single_source_artists.

*/

with genre_rows as (

    select
        artist_id,
        source,
        discogs_genre
    from {{ ref('int_source_tag_classification') }}
    where classification_status = 'genre'

),

style_rows as (

    select
        artist_id,
        source,
        discogs_style
    from {{ ref('int_source_tag_classification') }}
    where classification_status = 'genre'
      and discogs_style is not null

),

per_source as (

    select
        artist_id,
        source,
        discogs_genre
    from genre_rows

    group by
        artist_id,
        source,
        discogs_genre

),

per_source_styles as (

    select
        artist_id,
        source,
        discogs_style
    from style_rows

    group by
        artist_id,
        source,
        discogs_style

),

source_counts as (

    select
        artist_id,
        count(distinct source) as nb_sources
    from per_source
    group by artist_id

),

qualified_artists as (

    select artist_id
    from source_counts
    where nb_sources >= 2

),

lastfm_sets as (

    select
        artist_id,
        list(discogs_genre order by discogs_genre) as genres_lastfm
    from per_source
    where source = 'lastfm'
    group by artist_id

),

musicbrainz_sets as (

    select
        artist_id,
        list(discogs_genre order by discogs_genre) as genres_musicbrainz
    from per_source
    where source = 'musicbrainz'
    group by artist_id

),

rapidapi_sets as (

    select
        artist_id,
        list(discogs_genre order by discogs_genre) as genres_rapidapi
    from per_source
    where source = 'rapidapi'
    group by artist_id

),

genre_source_freq as (

    select
        artist_id,
        discogs_genre,
        count(distinct source) as nb_sources_with_genre
    from per_source
    group by
        artist_id,
        discogs_genre

),

shared as (

    select
        artist_id,
        list(discogs_genre order by discogs_genre) as shared_genres,
        count(*) as nb_shared_genres
    from genre_source_freq
    where nb_sources_with_genre >= 2
    group by artist_id

),

unioned as (

    select
        artist_id,
        list(discogs_genre order by discogs_genre) as union_genres,
        count(*) as nb_union_genres
    from (
        select distinct
            artist_id,
            discogs_genre
        from per_source
    )
    group by artist_id

),

/*
    Style level: same construction as genres, style-name-only matching.
*/
lastfm_style_sets as (

    select
        artist_id,
        list(discogs_style order by discogs_style) as styles_lastfm
    from per_source_styles
    where source = 'lastfm'
    group by artist_id

),

musicbrainz_style_sets as (

    select
        artist_id,
        list(discogs_style order by discogs_style) as styles_musicbrainz
    from per_source_styles
    where source = 'musicbrainz'
    group by artist_id

),

rapidapi_style_sets as (

    select
        artist_id,
        list(discogs_style order by discogs_style) as styles_rapidapi
    from per_source_styles
    where source = 'rapidapi'
    group by artist_id

),

style_source_freq as (

    select
        artist_id,
        discogs_style,
        count(distinct source) as nb_sources_with_style
    from per_source_styles
    group by
        artist_id,
        discogs_style

),

shared_styles as (

    select
        artist_id,
        list(discogs_style order by discogs_style) as shared_styles,
        count(*) as nb_shared_styles
    from style_source_freq
    where nb_sources_with_style >= 2
    group by artist_id

),

unioned_styles as (

    select
        artist_id,
        list(discogs_style order by discogs_style) as union_styles,
        count(*) as nb_union_styles
    from (
        select distinct
            artist_id,
            discogs_style
        from per_source_styles
    )
    group by artist_id

),

style_source_counts as (

    select
        artist_id,
        count(distinct source) as nb_style_sources
    from per_source_styles
    group by artist_id

)

select

    q.artist_id,

    min(c.spotify_artist_name) as spotify_artist_name,

    sc.nb_sources,

    list(distinct p.source order by p.source) as sources,

    coalesce(l.genres_lastfm, []) as genres_lastfm,
    coalesce(mb.genres_musicbrainz, []) as genres_musicbrainz,
    coalesce(r.genres_rapidapi, []) as genres_rapidapi,

    coalesce(sh.shared_genres, []) as shared_genres,
    coalesce(u.union_genres, []) as union_genres,

    coalesce(sh.nb_shared_genres, 0) as nb_shared_genres,
    u.nb_union_genres,

    round(
        coalesce(sh.nb_shared_genres, 0) / nullif(u.nb_union_genres, 0),
        4
    ) as agreement_score,

    /*
        Style level. nb_style_sources gates scoring: fewer than 2
        sources with styles -> no style comparison possible.
    */
    coalesce(lst.styles_lastfm, []) as styles_lastfm,
    coalesce(mbst.styles_musicbrainz, []) as styles_musicbrainz,
    coalesce(rst.styles_rapidapi, []) as styles_rapidapi,

    coalesce(shst.shared_styles, []) as shared_styles,
    coalesce(ust.union_styles, []) as union_styles,

    coalesce(shst.nb_shared_styles, 0) as nb_shared_styles,
    coalesce(ust.nb_union_styles, 0) as nb_union_styles,

    case
        when ssc.nb_style_sources >= 2 then round(
            coalesce(shst.nb_shared_styles, 0) / nullif(ust.nb_union_styles, 0),
            4
        )
        else null
    end as subgenre_agreement_score

from qualified_artists q

inner join source_counts sc
    using (artist_id)

inner join per_source p
    using (artist_id)

left join lastfm_sets l
    using (artist_id)

left join musicbrainz_sets mb
    using (artist_id)

left join rapidapi_sets r
    using (artist_id)

left join shared sh
    using (artist_id)

left join unioned u
    using (artist_id)

left join lastfm_style_sets lst
    using (artist_id)

left join musicbrainz_style_sets mbst
    using (artist_id)

left join rapidapi_style_sets rst
    using (artist_id)

left join shared_styles shst
    using (artist_id)

left join unioned_styles ust
    using (artist_id)

left join style_source_counts ssc
    using (artist_id)

left join {{ ref('int_source_tag_classification') }} c
    using (artist_id)

group by
    q.artist_id,
    sc.nb_sources,
    l.genres_lastfm,
    mb.genres_musicbrainz,
    r.genres_rapidapi,
    sh.shared_genres,
    sh.nb_shared_genres,
    u.union_genres,
    u.nb_union_genres,
    lst.styles_lastfm,
    mbst.styles_musicbrainz,
    rst.styles_rapidapi,
    shst.shared_styles,
    shst.nb_shared_styles,
    ust.union_styles,
    ust.nb_union_styles,
    ssc.nb_style_sources
