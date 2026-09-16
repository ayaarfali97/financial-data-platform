with raw as (
    select
        ticker,
        cik,
        concept,
        unit,
        value,
        fy,
        fp,
        form,
        period_start,
        period_end,
        filed,
        accn,
        case
            when period_start is null then 'instant'
            when (period_end - period_start) between 80 and 100  then 'quarter'
            when (period_end - period_start) between 170 and 190 then 'half'
            when (period_end - period_start) between 260 and 285 then 'ytd9m'
            when (period_end - period_start) between 350 and 380 then 'annual'
            else 'other'
        end as period_type
    from {{ source('raw', 'financial_facts') }}
    where value is not null
),

-- canonicalise the messy us-gaap tags into a small set of metric names
mapped as (
    select
        *,
        case concept
            when 'Revenues' then 'revenue'
            when 'RevenueFromContractWithCustomerExcludingAssessedTax' then 'revenue'
            when 'CostOfRevenue' then 'cost_of_revenue'
            when 'CostOfGoodsAndServicesSold' then 'cost_of_revenue'
            when 'GrossProfit' then 'gross_profit'
            when 'OperatingIncomeLoss' then 'operating_income'
            when 'OperatingExpenses' then 'operating_expenses'
            when 'ResearchAndDevelopmentExpense' then 'rnd_expense'
            when 'NetIncomeLoss' then 'net_income'
            when 'Assets' then 'assets'
            when 'Liabilities' then 'liabilities'
            when 'StockholdersEquity' then 'equity'
            when 'CashAndCashEquivalentsAtCarryingValue' then 'cash'
            when 'EarningsPerShareBasic' then 'eps_basic'
            when 'EarningsPerShareDiluted' then 'eps_diluted'
            else null
        end as metric
    from raw
),

-- one value per (ticker, metric, period, period_type): keep the most recently filed
deduped as (
    select *,
        row_number() over (
            partition by ticker, metric, unit, period_end, period_type
            order by filed desc, accn desc
        ) as rn
    from mapped
    where metric is not null
)

select
    ticker,
    cik,
    metric,
    unit,
    value,
    fy,
    fp,
    form,
    period_type,
    period_start,
    period_end,
    filed
from deduped
where rn = 1
