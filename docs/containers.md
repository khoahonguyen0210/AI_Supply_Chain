# Containers and the local stack

## One command

```bash
bash scripts/stack.sh up      # first run: creates .env with random local secrets, builds, waits for health
bash scripts/stack.sh smoke   # planner workflow through the running frontend (tests/smoke)
bash scripts/stack.sh down    # stop (data kept); `reset` also deletes the volumes
```

`up` prints the frontend URL (http://localhost:3000) and the demo password. The demo accounts are `planner`,
`manager` (procurement manager), `finance` and `admin`, one per role. Needs Docker with Compose v2 and bash (Git Bash
on Windows); nothing else is installed on the host.

## Images

| Image | Dockerfile | Contents | Size (measured) |
|---|---|---|---|
| `scm-backend` | `infrastructure/docker/backend.Dockerfile` | Spring Boot jar on a JRE: API, job workers, Flyway migrations | 533 MB |
| `scm-ml` | `infrastructure/docker/ml.Dockerfile` | Python engine (forecast, sourcing, optimisation, scenarios, RAG, agent) and its CLIs; the synthetic forecast model is trained and the bge-small embedding model downloaded at build time | 1.04 GB |
| `scm-frontend` | `infrastructure/docker/frontend.Dockerfile` | Next.js standalone server | 297 MB |

All three are multi-stage builds that run as a non-root user and define a `HEALTHCHECK`. Builds are reproducible from a
source revision: `uv.lock`, `package-lock.json` and the Maven wrapper pin dependencies, and the model trained during
the build is deterministic (fixed seed). Each Dockerfile has its own `*.Dockerfile.dockerignore` that keeps the build
context to the sources it needs. The frontend proxies `/api/*` to `BACKEND_URL`, which Next.js fixes at build time, so
it is a build argument (default `http://backend:8080`, the service name in both Compose and Kubernetes).

## Compose services (`compose.yaml`)

| Service | Role | Health | Published |
|---|---|---|---|
| `postgres` | pgvector PostgreSQL 16: records, job queue, knowledge base | `pg_isready` | 127.0.0.1:5432 |
| `backend` | API and job worker; runs the migrations at startup | `/actuator/health` on 8081 | 127.0.0.1:8080 (API), 127.0.0.1:8081 (metrics) |
| `seed` | one-shot: loads the synthetic company once the schema exists (idempotent) | exits 0 | - |
| `engine` | planning engine; syncs the policy corpus into pgvector at startup | `/health` | not published (it trusts the actor the backend names) |
| `frontend` | the UI | `GET /` | 127.0.0.1:3000 |

Start order: postgres -> backend -> seed -> engine, with frontend after the backend. `docker compose up --wait`
returns only when every long-running service is healthy and the seed has completed. Everything binds to localhost.
The engine keeps agent tasks and approvals in a SQLite file on the `engine-state` volume, so they survive restarts;
`SCM_ML_PLANNER=claude` plus `ANTHROPIC_API_KEY` in `.env` switches the copilot to Claude.

## Verified

On Windows 11 with Docker Desktop (Compose v5.5.1): a cold `up` (images built from scratch) brings every service to
healthy; `smoke` passes its four checks (frontend and auth boundary, seeded data, question -> recommendation ->
approval by the required roles -> approved, a queued optimisation job). A second `up` on existing volumes took
2 min 35 s (rebuild from cache, seed re-applied without changes) and `smoke` passed again.
