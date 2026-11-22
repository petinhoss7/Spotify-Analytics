/*

    Row-level scored genre tags - the single definition of the
    tag-level evidence weight used by the attribution model and the
    listening marts.

    Grain: 1 row = 1 artist x 1 source x 1 raw tag classified to a
    Discogs genre (classification_status = 'genre' in
    int_source_tag_classification).

    Two independent reliability factors, multiplied:

        method_weight: reliability of the *mechanism*
            manual / exact / alias 1.0, fuzzy 0.9, llm 0.8
        confidence: reliability of the *tag meaning* (from the seed,
            1.0 by default). seeds/tag_overrides.csv lowers it for tags
            that do not determine a genre by themselves ("dance",
            "lo-fi", "oldies"...), so an artist's specific genre tags
            outrank generic ones.

        row_weight = method_weight x confidence x ln(1 + tag_count)
            tag_count: source popularity weight (Last.fm listener count /
            MusicBrainz vote count), null -> 1

*/

with genre_tags as (

    select
        artist_id,
        spotify_artist_name,
        source,
        raw_tag,
        discogs_genre,
        discogs_style,
        tag_count,
        case
            when match_method in ('manual', 'exact', 'alias') then 1.0
            when match_method = 'fuzzy' then 0.9
            else 0.8
        end as method_weight,
        coalesce(confidence, 1.0) as confidence

    from {{ ref('int_source_tag_classification') }}
    where classification_status = 'genre'

)

select

    artist_id,
    spotify_artist_name,
    source,
    raw_tag,
    discogs_genre,
    discogs_style,
    tag_count,
    method_weight,
    confidence,

    method_weight * confidence * ln(1 + coalesce(tag_count, 1)) as row_weight

from genre_tags
