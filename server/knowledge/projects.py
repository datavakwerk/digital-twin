# Real content drafted from ruudjuffermans.nl and github.com/datavakwerk
# (checked 2026-08-22). TODO(Ruud): review, add outcomes you want public.

TITLE = "Projects"

CONTENT = """\
## Ask Ruud — this assistant (2026)
The AI assistant you are talking to right now. FastAPI backend proxying the
Claude API with streaming SSE, native citations, prompt caching, rate limiting
and per-message cost telemetry; React front end with a live "under the hood"
panel. Pluggable backend runs on a local Ollama container during development.

## Open data warehouse — Kimball star schema on RDW and CBS data
End-to-end ELT platform on Dutch open (vehicle) data: Python ingestion, dbt
transformations, and a documented star schema with three explicit grains.
Tests, linting and build validation run in CI on every pull request, and the
whole warehouse builds from scratch with a single command. Warehouse-agnostic
modelling on DuckDB, portable to Snowflake or Databricks.
Source: github.com/datavakwerk/nl-vehicle-warehouse

## Realtime OV streaming pipeline
Streaming pipeline on Kafka that tracks Dutch public transport vehicle
positions in real time: five-minute windows, a dead-letter queue with replay,
and a live delay map. Fully observable with Prometheus and Grafana, and
durability-tested over a 24-hour run. Python, Postgres, Docker.
Source: github.com/datavakwerk/ov-streaming-pipeline

## Strafrecht RAG — grounded QA over Dutch case law
A RAG system over published rulings from Rechtspraak.nl: questions in plain
language, answers based exclusively on retrieved passages, always with an
ECLI citation back to the source ruling. Retrieval quality is guarded by
recall tests in CI — the same grounded-QA discipline this assistant uses.
Source: github.com/datavakwerk/strafrecht-rag

## Teaching & writing

- Udemy courses on data topics since 2020, with thousands of students.
- Blog posts on ruudjuffermans.nl about data platforms and AI.
"""
