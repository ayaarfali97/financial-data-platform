select
    transcript_id,
    ticker,
    company     as company_name,
    call_date,
    fiscal_year,
    quarter,
    doc_type,
    source,
    n_chars,
    content
from {{ source('raw', 'transcripts') }}
