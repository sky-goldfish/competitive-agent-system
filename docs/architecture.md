# Architecture

MVP uses a two-stage orchestration around LangGraph-compatible nodes:

1. `start_run`: requirement understanding -> competitor discovery -> human confirmation wait
2. `confirm_and_continue_run`: material collection -> structured analysis -> report generation

The implementation stores all run data in SQLite and exposes FastAPI endpoints for the React frontend.
