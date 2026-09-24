# Archived: early connections-module prototype

These 5 files (`postgres.py`, `chromadb.py`, `connections.py`, `fetch_user.py`, `pgvector.py`)
were an early prototype of the connections module, built against a `"Users"` table (columns like
`min_quantity_mt`) that predates the current `Profile`/`Business`/`Commodity` schema. That table
no longer exists in the database.

They were superseded before this cutover by the real implementation at
`app/modules/connections/data/repository.py` + `app/modules/connections/application/use_cases/service.py`,
which reads/writes the current schema and does its vector recommendation search against the
`user_embeddings` table (shared with post/profile).

Confirmed zero real importers anywhere in `app/` before archiving. Kept here for reference only —
**do not import from this directory**. `postgres.py` in particular prints the database URL to
stdout and opens a second async DB engine with `echo=True` if it's ever loaded.
