-- Theme mention counts per earnings call. Gives the vector/transcript layer a
-- structured companion table (one row per transcript) that joins to dim_company
-- and dim_date. Counts use word-boundary regex on the transcript body.
with base as (
    select
        transcript_id,
        ticker,
        company_name,
        call_date,
        fiscal_year,
        quarter,
        n_chars,
        lower(content) as body
    from {{ ref('stg_transcripts') }}
)
select
    transcript_id,
    ticker,
    company_name,
    call_date,
    fiscal_year,
    quarter,
    n_chars,
    regexp_count(body, '\y(ai|artificial intelligence|machine learning)\y') as mentions_ai,
    regexp_count(body, '\y(cloud|azure|aws|gcp)\y')                         as mentions_cloud,
    regexp_count(body, '\y(data center|datacenter)\y')                      as mentions_datacenter,
    regexp_count(body, '\y(gaming|game)\y')                                 as mentions_gaming,
    regexp_count(body, '\y(supply chain|shortage|constraint)\y')            as mentions_supply_chain,
    regexp_count(body, '\y(guidance|outlook|forecast)\y')                   as mentions_guidance,
    regexp_count(body, '\y(buyback|repurchase|dividend)\y')                 as mentions_capital_return,
    regexp_count(body, '\y(headwind|macro|uncertain|weak)\y')              as mentions_headwind,
    regexp_count(body, '\y(record|strong|growth|accelerat)\y')             as mentions_positive
from base
