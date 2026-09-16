-- Pre-calculated quarterly KPIs: margins, R&D intensity, and YoY / QoQ growth.
-- Grain: one row per (ticker, fiscal quarter).
--
-- NOTE on YoY: EDGAR does not expose a discrete 3-month value for every fiscal
-- quarter (the September quarter is typically only in the 10-K), so quarters can
-- be unevenly spaced. We therefore compute YoY by matching the SAME calendar
-- quarter one year earlier via self-join, not a positional lag(4).
with q as (
    select
        ticker,
        period_end,
        extract(year from period_end)::int    as cal_year,
        extract(quarter from period_end)::int as cal_quarter,
        year,
        quarter,
        year_quarter,
        fiscal_year,
        revenue,
        gross_profit,
        operating_income,
        net_income,
        rnd_expense,
        eps_diluted
    from {{ ref('fact_financial_metrics') }}
    where grain = 'quarter'
),

yoy as (
    select
        cur.*,
        prior.revenue    as revenue_yago,
        prior.net_income as net_income_yago,
        lag(cur.revenue) over (partition by cur.ticker order by cur.period_end) as revenue_prev_q
    from q cur
    left join q prior
      on prior.ticker = cur.ticker
     and prior.cal_quarter = cur.cal_quarter
     and prior.cal_year = cur.cal_year - 1
)

select
    ticker,
    period_end,
    year,
    quarter,
    year_quarter,
    fiscal_year,
    revenue,
    gross_profit,
    operating_income,
    net_income,
    rnd_expense,
    eps_diluted,
    round((gross_profit::numeric     / nullif(revenue, 0)) * 100, 2) as gross_margin_pct,
    round((operating_income::numeric / nullif(revenue, 0)) * 100, 2) as operating_margin_pct,
    round((net_income::numeric       / nullif(revenue, 0)) * 100, 2) as net_margin_pct,
    round((rnd_expense::numeric      / nullif(revenue, 0)) * 100, 2) as rnd_intensity_pct,
    round(((revenue::numeric    / nullif(revenue_yago, 0)) - 1) * 100, 2)   as revenue_yoy_growth_pct,
    round(((revenue::numeric    / nullif(revenue_prev_q, 0)) - 1) * 100, 2) as revenue_qoq_growth_pct,
    round(((net_income::numeric / nullif(net_income_yago, 0)) - 1) * 100, 2) as net_income_yoy_growth_pct
from yoy
