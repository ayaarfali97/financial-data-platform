-- Clean full-year figures. EDGAR exposes several annual entries per company
-- (restatements, differing fiscal-year contexts, and rows where only some
-- metrics are present), so we keep ONE row per (ticker, calendar year): the
-- period-end in that year whose row is most complete (revenue present first,
-- then latest period_end). Full-year revenue here is authoritative, unlike
-- summing quarters (some 3-month periods are absent in EDGAR).
with annual as (
    select
        ticker,
        extract(year from period_end)::int as year,
        period_end,
        revenue, cost_of_revenue, gross_profit, operating_income,
        rnd_expense, net_income, eps_diluted, assets, liabilities, equity, cash
    from {{ ref('fact_financial_metrics') }}
    where grain = 'annual'
),

ranked as (
    select *,
        row_number() over (
            partition by ticker, year
            order by (revenue is not null) desc, period_end desc
        ) as rn
    from annual
),

deduped as (
    select * from ranked where rn = 1 and revenue is not null
),

with_growth as (
    select *,
        lag(revenue)    over (partition by ticker order by year) as revenue_prev,
        lag(net_income) over (partition by ticker order by year) as net_income_prev
    from deduped
)

select
    ticker,
    year,
    period_end,
    revenue,
    gross_profit,
    operating_income,
    net_income,
    rnd_expense,
    eps_diluted,
    assets,
    liabilities,
    equity,
    cash,
    round((gross_profit::numeric     / nullif(revenue, 0)) * 100, 2) as gross_margin_pct,
    round((operating_income::numeric / nullif(revenue, 0)) * 100, 2) as operating_margin_pct,
    round((net_income::numeric       / nullif(revenue, 0)) * 100, 2) as net_margin_pct,
    round((rnd_expense::numeric      / nullif(revenue, 0)) * 100, 2) as rnd_intensity_pct,
    round(((revenue::numeric    / nullif(revenue_prev, 0)) - 1) * 100, 2)    as revenue_yoy_growth_pct,
    round(((net_income::numeric / nullif(net_income_prev, 0)) - 1) * 100, 2) as net_income_yoy_growth_pct
from with_growth
