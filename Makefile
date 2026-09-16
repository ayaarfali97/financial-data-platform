.PHONY: help up down db-only ingest dbt ml router eval dashboard pipeline logs clean

VENV ?= .venv/bin
DBT_DIR = dbt/financial_warehouse
PG_ENV = POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_USER=fdp POSTGRES_PASSWORD=fdp_local_pw POSTGRES_DB=financial

help:
	@echo "Financial Data Platform — targets:"
	@echo "  make up         # start postgres+pgvector (docker compose)"
	@echo "  make ingest     # Ingestion Agent: EDGAR + transcripts + embeddings"
	@echo "  make dbt        # Modeling Agent: build dbt warehouse + tests"
	@echo "  make ml         # ML Agent: sentiment model -> ml_outputs"
	@echo "  make eval       # Eval Agent: run Q&A set against the router"
	@echo "  make router Q='your question'   # ask the Query Router Agent"
	@echo "  make dashboard  # run Streamlit dashboard on :8501"
	@echo "  make pipeline   # ingest -> dbt -> ml -> eval end to end"
	@echo "  make down       # stop containers"

up:
	docker compose up -d postgres

db-only: up

ingest:
	$(VENV)/python -m agents.ingestion.ingest

dbt:
	cd $(DBT_DIR) && $(PG_ENV) ../../$(VENV)/dbt run --profiles-dir . && \
	                 $(PG_ENV) ../../$(VENV)/dbt test --profiles-dir .

ml:
	$(VENV)/python -m agents.ml.train_sentiment

router:
	$(VENV)/python -m agents.router.router "$(Q)"

eval:
	$(VENV)/python -m agents.eval.eval --json

dashboard:
	$(VENV)/streamlit run dashboard/app.py --server.port 8501

pipeline: ingest dbt ml eval
	@echo "pipeline complete"

down:
	docker compose down

logs:
	docker compose logs -f postgres

clean:
	docker compose down -v
