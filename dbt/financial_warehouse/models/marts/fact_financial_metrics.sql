-- One row per (company, period_end, grain). Flow metrics (income statement)
-- come from 'quarter'/'annual' duration facts; balance-sheet metrics come from
-- 'instant' facts matched on period_end; EPS is per-share.
with flows as (
    select
        ticker, period_end, period_type, fy, fp,
        max(value) filter (where metric = 'revenue')           as revenue,
        max(value) filter (where metric = 'cost_of_revenue')   as cost_of_revenue,
        max(value) filter (where metric = 'gross_profit')      as gross_profit,
        max(value) filter (where metric = 'operating_income')  as operating_income,
        max(value) filter (where metric = 'operating_expenses') as operating_expenses,
        max(value) filter (where metric = 'rnd_expense')       as rnd_expense,
        max(value) filter (where metric = 'net_income')        as net_income
    from {{ ref('stg_financial_facts') }}
    where unit = 'USD'
      and period_type in ('quarter', 'annual')
    group by ticker, period_end, period_type, fy, fp
),

balances as (
    select
        ticker, period_end,
        max(value) filter (where metric = 'assets')      as assets,
        max(value) filter (where metric = 'liabilities') as liabilities,
        max(value) filter (where metric = 'equity')      as equity,
        max(value) filter (where metric = 'cash')        as cash
    from {{ ref('stg_financial_facts') }}
    where unit = 'USD' and period_type = 'instant'
    group by ticker, period_end
),

eps as (
    select
        ticker, period_end, period_type,
        max(value) filter (where metric = 'eps_diluted') as eps_diluted,
        max(value) filter (where metric = 'eps_basic')   as eps_basic
    from {{ ref('stg_financial_facts') }}
    where metric in ('eps_diluted', 'eps_basic')
      and period_type in ('quarter', 'annual')
    group by ticker, period_end, period_type
)

select
    f.ticker,
    f.period_end,
    f.period_type                          as grain,
    d.year,
    d.quarter,
    d.year_quarter,
    f.fy                                   as fiscal_year,
    f.fp                                   as fiscal_period,
    f.revenue,
    f.cost_of_revenue,
    coalesce(f.gross_profit, f.revenue - f.cost_of_revenue) as gross_profit,
    f.operating_income,
    f.operating_expenses,
    f.rnd_expense,
    f.net_income,
    e.eps_diluted,
    e.eps_basic,
    b.assets,
    b.liabilities,
    b.equity,
    b.cash
from flows f
left join balances b using (ticker, period_end)
left join eps e using (ticker, period_end, period_type)
left join {{ ref('dim_date') }} d on d.date_day = f.period_end
