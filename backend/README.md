# Covenia backend scaffold

This BATCH-02 artifact establishes the installable Python package and test
conventions used by later backend work. It contains no business routes, domain
rules, database tables, importers, model calls, or frontend integration.

## Runtime

The lock was validated with CPython 3.13.5 on Windows. It is CPU-only: no GPU
framework or model runtime is installed.

From the repository root, create an isolated environment and install the lock:

```powershell
python -m venv reports/batches/BATCH-02/runtime/venv
.\reports\batches\BATCH-02\runtime\venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.lock
python -m pip install --no-deps -e backend
```

The package is named `covenia_b`. The ASGI application is available as
`covenia_b.main:app`; an explicit `create_app()` factory is also provided.
It does not connect to a model, SQLite, images, or another service during
import or startup. It has no domain endpoints, and the generated API-document
routes are disabled until a later contract-owning batch adds them.

For a local ASGI-process smoke check only (not a business integration test):

```powershell
python -m uvicorn covenia_b.main:app --host 127.0.0.1 --port 8000
```

## Configuration

[.env.example](.env.example) is a non-secret inventory of the variables that
later components may use. The bootstrap reads only explicitly supplied
`COVENIA_` environment variables; it does not automatically load a `.env`
file and never logs configuration values. `COVENIA_PII_SAFETY_CHECKS_ENABLED`
defaults to `true` and must not be disabled to run the bootstrap tests.

| Variable | Non-secret example | Bootstrap behavior |
| --- | --- | --- |
| `COVENIA_MODEL_ENDPOINT` | `http://127.0.0.1:8001` | Stored only; no connection is made. |
| `COVENIA_IMAGE_ROOT` | `./data/images` | Stored only; no files are read. |
| `COVENIA_SQLITE_PATH` | `./runtime/covenia.sqlite3` | Stored only; no database is opened. |
| `COVENIA_ALLOWED_ORIGIN` | `http://localhost:5173` | Stored for later transport configuration. |
| `COVENIA_DEMO_CLOCK` | `system` | Stored for later runtime composition. |
| `COVENIA_CACHE_MODE` | `disabled` | Stored for later cache composition. |
| `COVENIA_PII_SAFETY_CHECKS_ENABLED` | `true` | Defaults to `true`. |

## Verification conventions

```powershell
python -m pytest backend/tests/test_bootstrap.py -q
python -m ruff check backend/src/covenia_b/main.py backend/src/covenia_b/settings.py backend/src/covenia_b/api/base.py
python -m build backend --outdir reports/batches/BATCH-02/build
```

The registered pytest markers are `live`, `http`, `e2e`, and `mutation`.
They are declarations for later batches, not claims that real model, HTTP,
browser, or mutation verification has run in this scaffold.

## Extension seams

- `covenia_b.settings.Settings` reads safe process-environment configuration.
- `covenia_b.main.create_app()` constructs the empty FastAPI app.
- `covenia_b.api.base` centralizes request-ID normalization and the generic
  error envelope. Later API modules may use this seam after the contract batch
  defines the four business interfaces.
