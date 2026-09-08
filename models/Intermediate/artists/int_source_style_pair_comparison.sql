/*

    Style (sous-genre) agreement between source pairs - sibling of
    int_source_genre_pair_comparison at the style level.

    Grain: 1 row = 1 source_pair x style_a x style_b.

    Matching is style-name-only: a style co-occurrence is counted even
    when the two sources place the style under different genres
    (genre divergence is measured in the genre pair model).

    The diagonal (style_a = style_b) counts agreeing artists;
    off-diagonal cells expose systematic style confusions between the
    two sources (e.g. Synth-pop vs New Wave).

    mean_pair_style_jaccard and nb_artists_compared are attributes of
    the source pair, repeated on each of its rows.

*/

with style_rows as (

    select
        artist_id,
        source,
        discogs_style
    from {{ ref('int_source_tag_classification') }}
    where classification_status = 'genre'
      and discogs_style is not null

),

distinct_styles as (

    select distinct
        artist_id,
        source,
        discogs_style
    from style_rows

),

crossed as (

    select
        a.source as source_a,
        b.source as source_b,
        a.discogs_style as style_a,
        b.discogs_style as style_b,
        a.artist_id
    from distinct_styles a
    inner join distinct_styles b
        on a.artist_id = b.artist_id
       and a.source < b.source

),

pair_counts as (

    select
        source_a,
        source_b,
        style_a,
        style_b,
        count(distinct artist_id) as nb_artists
    from crossed
    group by
        source_a,
        source_b,
        style_a,
        style_b

),

/*

    Per-artist, per-pair Jaccard between the two style sets.
*/
artist_pair_sets as (

    select
        a.source as source_a,
        b.source as source_b,
        a.artist_id,
        count(distinct case
            when a.discogs_style = b.discogs_style
            then a.discogs_style
        end) as nb_shared,
        count(distinct a.discogs_style)
            + count(distinct b.discogs_style)
            - count(distinct case
                when a.discogs_style = b.discogs_style
                then a.discogs_style
            end) as nb_union
    from distinct_styles a
    inner join distinct_styles b
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
        ) as mean_pair_style_jaccard
    from artist_pair_sets
    group by
        source_a,
        source_b

)

select

    pc.source_a,
    pc.source_b,
    pc.style_a,
    pc.style_b,
    pc.nb_artists,
    case
        when pc.style_a = pc.style_b then true
        else false
    end as is_agreement,

    psum.nb_artists_compared,
    psum.mean_pair_style_jaccard

from pair_counts pc

inner join pair_summary psum
    using (source_a, source_b)
