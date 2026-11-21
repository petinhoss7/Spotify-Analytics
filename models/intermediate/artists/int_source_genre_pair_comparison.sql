/*

    Genre-level agreement between source pairs.

    Grain: 1 row = 1 source_pair x genre_a x genre_b.

    For every artist genre-classified by two sources, the two genre
    sets are crossed: each (genre_a, genre_b) co-occurrence counts
    the artists for which source A said genre_a while source B said
    genre_b. The diagonal (genre_a = genre_b) shows agreement;
    off-diagonal cells expose systematic disagreements
    (confusion-matrix view).

    mean_pair_jaccard and nb_artists_compared are attributes of the
    source pair, repeated on each of its rows.

*/

with genre_rows as (

    select
        artist_id,
        source,
        discogs_genre
    from {{ ref('int_source_tag_classification') }}
    where classification_status = 'genre'

),

distinct_genres as (

    select distinct
        artist_id,
        source,
        discogs_genre
    from genre_rows

),

crossed as (

    select
        a.source as source_a,
        b.source as source_b,
        a.discogs_genre as genre_a,
        b.discogs_genre as genre_b,
        a.artist_id
    from distinct_genres a
    inner join distinct_genres b
        on a.artist_id = b.artist_id
       and a.source < b.source

),

pair_counts as (

    select
        source_a,
        source_b,
        genre_a,
        genre_b,
        count(distinct artist_id) as nb_artists
    from crossed
    group by
        source_a,
        source_b,
        genre_a,
        genre_b

),

/*

    Per-artist, per-pair Jaccard between the two genre sets.
*/
artist_pair_sets as (

    select
        a.source as source_a,
        b.source as source_b,
        a.artist_id,
        count(distinct case
            when a.discogs_genre = b.discogs_genre
            then a.discogs_genre
        end) as nb_shared,
        count(distinct a.discogs_genre)
            + count(distinct b.discogs_genre)
            - count(distinct case
                when a.discogs_genre = b.discogs_genre
                then a.discogs_genre
            end) as nb_union
    from distinct_genres a
    inner join distinct_genres b
        on a.artist_id = b.artist_id
       and a.source < b.source
    group by
        a.source,
        b.source,
        a.artist_id

),

pair_summary as (

    select
        source_a,
        source_b,
        count(*) as nb_artists_compared,
        round(
            avg(nb_shared / nullif(nb_union, 0)::double),
            4
        ) as mean_pair_jaccard
    from artist_pair_sets
    group by
        source_a,
        source_b

)

select

    pc.source_a,
    pc.source_b,
    pc.genre_a,
    pc.genre_b,
    pc.nb_artists,
    case
        when pc.genre_a = pc.genre_b then true
        else false
    end as is_agreement,

    psum.nb_artists_compared,
    psum.mean_pair_jaccard

from pair_counts pc

inner join pair_summary psum
    using (source_a, source_b)
