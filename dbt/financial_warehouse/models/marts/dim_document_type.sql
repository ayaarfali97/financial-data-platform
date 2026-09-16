-- Small dimension of document types present in the vector/transcript layer.
select
    doc_type                                    as document_type,
    count(*)                                    as n_documents,
    min(call_date)                              as first_seen,
    max(call_date)                              as last_seen
from {{ ref('stg_transcripts') }}
group by doc_type
