select
    ticker,
    name        as company_name,
    cik,
    sector
from {{ source('raw', 'company') }}
