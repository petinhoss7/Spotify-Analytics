-- Every staging tag must have a map entry: no artist x tag line may be
-- left unmapped (the map covers the full staging vocabulary).
select
    source,
    raw_tag,
    count(*) as nb_rows
from {{ ref('int_source_tag_classification') }}
where classification_status = 'unmapped'
group by
    source,
    raw_tag
