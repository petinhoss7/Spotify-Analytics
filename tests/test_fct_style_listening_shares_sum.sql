-- The split must be complete: the style shares of every month must sum to 1
-- (all attributed styles + the three buckets).
select
    listening_month,
    sum(share_of_month_minutes) as total_share
from {{ ref('fct_style_listening') }}
group by listening_month
having abs(sum(share_of_month_minutes) - 1) > 0.001
