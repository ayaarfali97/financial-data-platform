with financials as (
    select ticker, min(period_end) as first_period, max(period_end) as last_period
    from {{ ref('stg_financial_facts') }}
    group by ticker
)
select
    c.ticker,
    c.company_name,
    c.cik,
    c.sector,
    f.first_period,
    f.last_period
from {{ ref('stg_companies') }} c
left join financials f using (ticker)
