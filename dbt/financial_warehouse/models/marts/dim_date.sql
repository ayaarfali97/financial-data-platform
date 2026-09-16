-- Calendar dimension built from every date that appears in the warehouse
-- (financial period ends + transcript call dates).
with dates as (
    select period_end as d from {{ ref('stg_financial_facts') }}
    union
    select call_date as d from {{ ref('stg_transcripts') }} where call_date is not null
)
select distinct
    d                                             as date_day,
    extract(year  from d)::int                    as year,
    extract(quarter from d)::int                  as quarter_num,
    'Q' || extract(quarter from d)::int           as quarter,
    extract(month from d)::int                    as month,
    to_char(d, 'YYYY') || '-Q' || extract(quarter from d)::int as year_quarter
from dates
where d is not null
