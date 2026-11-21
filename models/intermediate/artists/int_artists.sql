with spotify as (

    select *
    from {{ ref('stg_spotify_artists') }}

),

lastfm as (

    select *
    from {{ ref('stg_lastfm_artists') }}

),

musicbrainz as (

    select *
    from {{ ref('stg_musicbrainz_artists') }}

)

/*

    Consolidated artist profile.

    The final genre / sous-genre columns come from
    int_artists_genre_attribution (weighted-score attribution over the
    closed Discogs taxonomy): at most 2 genres and 2 styles per artist
    with confidence metadata. Artists without any genre-classified tag
    keep their row with null finals, and one_genre_found = false.

    Raw source tags are preserved as lists (spotify_genres, lastfm_genres,
    musicbrainz_genres) for drill-down; per-genre scoring detail lives in
    int_source_tag_classification / int_source_tag_cross_comparison.

*/

select

    s.artist_id,
    s.artist_name as spotify_artist_name,

    s.followers,
    s.popularity,

    s.genres as spotify_genres,

    l.found as lastfm_found,
    l.lastfm_artist_name,
    l.lastfm_tags as lastfm_genres,

    m.found as musicbrainz_found,
    m.musicbrainz_artist_name,
    m.tags as musicbrainz_genres,
    m.gender,
    m.country,
    m.begin_date,
    m.end_date,

    /*
        Final Discogs attribution (int_artists_genre_attribution).
    */
    ga.primary_genre,
    ga.primary_style,
    ga.secondary_genre,
    ga.secondary_style,

    ga.primary_share,
    ga.combined_confidence,
    ga.is_ambiguous,
    ga.nb_supporting_sources,

    case
        when ga.primary_genre is not null then true
        else false
    end as one_genre_found

from spotify s

left join lastfm l
    using (artist_id)

left join musicbrainz m
    using (artist_id)

left join {{ ref('int_artists_genre_attribution') }} ga
    using (artist_id)
