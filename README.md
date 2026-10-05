<div align="center">

# AI Supply Chain Planning & Optimization

**Forecast demand, choose suppliers and build the cheapest purchase plan, with people approving every order.**

![Java](https://img.shields.io/badge/Java-ED8B00?logo=openjdk&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring_Boot-6DB33F?logo=springboot&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-000000?logo=nextdotjs&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![LightGBM](https://img.shields.io/badge/LightGBM-2C8EBB)
![RAG](https://img.shields.io/badge/RAG_+_AI_agent-7C3AED)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?logo=kubernetes&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-844FBA?logo=terraform&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-232F3E)
![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

![Sign-in page](docs/images/home.png)

</div>

## What it does

Deciding what to buy for a supply chain usually means a pile of spreadsheets: guessing next month's sales,
comparing supplier quotes, checking whether the warehouses have room, and then waiting for someone to sign off.
This app brings all of that into one place. You ask a question in plain English, for example "Demand for
wireless earbuds is expected to rise by 20%. What should I do?", and it forecasts sales for each product and region,
compares suppliers on price, delivery time and reliability, and works out the cheapest purchase plan that still
respects every limit, from minimum order sizes to warehouse space and budget. It can also show what happens when
something goes wrong, such as a supplier that stops delivering, and it answers questions about company policies
and contracts by quoting the exact source. Every number it shows is looked up, never made up, and nothing is
ordered until the right managers approve it.

## Results

<div align="center">

![What the app achieved](docs/images/results.svg)

</div>

Compared with the simple way most teams plan today:

- **Better forecasts.** Sales forecasts are 11% more accurate than a simple 13-week average. On real data from
  an online store, the gain is smaller: 2.1%.
- **Cheaper plans.** Purchase plans cost 13% less than always buying from the cheapest supplier, and they stay
  within every limit (order sizes, supplier capacity, warehouse space). When the budget is cut by 15%, the plan
  still stays within budget, while the simple rules go over it.
- **Ready for problems.** If a supplier suddenly stops delivering, re-planning still covers 100% of demand,
  compared with 94% if you keep the old plan.
- **Right answers from documents.** For questions about policies and contracts, the right document comes up first
  94% of the time. Every answer shows its source, and people never see documents they aren't allowed to read.
- **Understands new requests.** On 20 requests it had never seen (scored once, before any change), the
  assistant handled 90% correctly.
- **Safe by design.** In all 100 test requests, it never placed an order without approval and never used
  a number that didn't come from real data.
- **Fast.** Most pages load in 10–60 ms, and a full assistant answer takes less than a second.

All results were measured on a made-up sample company, and every number comes from a saved result file in
`ml/experiments/`. What still doesn't work well is listed under [Limitations](#limitations), and the detailed
tables are in [`docs/benchmarks.md`](docs/benchmarks.md).

## How it works

```mermaid
flowchart LR
    Q[Planner asks a question] --> A[Assistant]
    A -->|question unclear| CL[Asks what you mean]
    A --> T{Tools}
    T --> FC[Forecast demand]
    T --> IN[Check stock]
    T --> SU[Rank suppliers]
    T --> OP[Build cheapest plan]
    T --> SC[Test what could go wrong]
    T --> RG[Look up policies and contracts]
    FC & IN & SU & OP & SC & RG --> G{Safety checks}
    G --> R[Proposed plan with sources]
    R --> AP{Manager approval}
    AP -->|approved| PO[(Orders and decision log)]
    PO --> OUT[What really happened] --> EV[Score the forecast and retrain if better]
```

Three parts work together:

- **Website** (Next.js): the pages planners and managers use.
- **Backend** (Java, Spring Boot): sign-in, permissions, approvals, background jobs and the audit log, all stored
  in PostgreSQL.
- **Planning engine** (Python): forecasting, supplier ranking, plan building, what-if tests, document search and
  the assistant.

## Every number has a source

<div align="center">

![Assistant answer with sources](docs/images/copilot.png)

</div>

- **No made-up numbers.** The assistant only uses numbers that a tool returned. A safety check blocks any answer
  that contains a number no tool produced.
- **It explains trade-offs.** For example, why the plan buys mostly from a supplier that isn't ranked first, or
  how much a supplier outage would cost if you keep the plan instead of re-planning.
- **It asks when unsure.** A question that names no product gets a follow-up question, not a guess.
- **You can see every step.** "How this was worked out" lists each tool it used, with its inputs and results.

Details: [`docs/agent.md`](docs/agent.md).

## A manager approves before anything is bought

The assistant can only prepare an order. The company's approval policy decides who must sign off, for example a
procurement manager for orders above $15,000. People can't approve their own requests, the assistant can't
approve anything, and every decision is saved permanently with the name of the person who made it. Details:
[`docs/security.md`](docs/security.md).

## Answers from policies and contracts

Questions like "Who must approve an order above $20,000?" are answered from 69 company documents. Each answer
names the document and its version. Old or expired versions are flagged, questions the documents can't answer
are declined, and people never see documents their role isn't allowed to read. Details:
[`docs/knowledge-retrieval.md`](docs/knowledge-retrieval.md).

## It learns, but only if the new model is better

When an order is approved, the app saves the forecast it was based on. Later, when real sales are recorded, it
compares the two. A retraining command builds a new forecast model from the new data and tests both models on
weeks that neither has seen. The new model replaces the old one only if it is more accurate, and only after a
named person approves the switch.

```bash
uv run python -m scm_ml.feedback retrain
uv run python -m scm_ml.feedback promote --report <report.json> --approved-by <name>
```

Details: [`docs/feedback-loop.md`](docs/feedback-loop.md).

## Tech stack

| Area | Tools |
|---|---|
| Languages | Java, Python, TypeScript, SQL, HCL (Terraform), CSS |
| Backend | Java 21, Spring Boot 4 (web, security with JWT, JDBC, validation, actuator), Flyway, Maven |
| Website | Next.js 16, React 19, TypeScript, Vitest, Testing Library, Playwright (screenshots) |
| Forecasting and planning | Python 3.12, LightGBM, NumPy, pandas, SciPy (HiGHS solver), FastAPI, Pydantic |
| Document search and assistant | fastembed (bge-small-en-v1.5), pgvector, BM25; optional Claude API |
| Data | PostgreSQL 16 with pgvector, a generated sample company, the Online Retail II dataset |
| Deployment | Docker Compose, Kubernetes (kind), Terraform for AWS (ECS Fargate, RDS, S3, EFS, ECR) |
| Monitoring | Micrometer, Prometheus endpoint, assistant usage stats, audit log |
| CI and quality | GitHub Actions (images pushed to GHCR), Trivy, pip-audit, npm audit, Ruff, mypy, pytest, JUnit, Testcontainers, actionlint, tflint, uv |

## Quick start

You need [Docker](https://www.docker.com/products/docker-desktop/), bash (Git Bash on Windows) and
[uv](https://docs.astral.sh/uv/). No API key or cloud account is needed.

**1. Start everything** (the first run builds the images, so it takes a few minutes):

```bash
bash scripts/stack.sh up
```

At the end, it prints the address and a password. The password is also saved in `.env` as `SCM_DEMO_PASSWORD`.

**2. Open http://localhost:3000.** Click **Create an account** to make your own (it can make plans and use the
assistant), or sign in with one of the four demo accounts, which all use that password:

| User id | What they can do |
|---|---|
| `planner` | ask the assistant, build plans, run what-if tests |
| `manager` | approve orders (procurement manager) |
| `finance` | approve large orders |
| `admin` | everything, plus the Monitoring page |

**3. Try the main flow:**

1. Sign in as `planner`, open **Assistant** and ask: *Demand for wireless earbuds is expected to rise by 20%. What should I do?*
2. Sign out, sign in as `manager`, open **Approvals** and approve the new request.
3. Do the same as `finance`. Only then is the order placed.

Or run the same story as a script: `uv run python -m scm_ml.demo --password <password>` (a recorded run is in
[`docs/demo.md`](docs/demo.md)).

**4. Stop it** with `bash scripts/stack.sh down` (your data stays), or `bash scripts/stack.sh reset` to delete the
data too.

| Service | Address |
|---|---|
| Website | http://localhost:3000 |
| Backend API | http://localhost:8080 |
| Metrics | http://localhost:8081/actuator/prometheus |

To run it on a local Kubernetes cluster instead: `bash scripts/kind.sh up` ([`docs/kubernetes.md`](docs/kubernetes.md)).

## Local development

This needs Java 21, Node.js 24 and uv.

```bash
uv sync --frozen                                         # Python environment
uv run python -m scm_ml.synthetic --out data/synthetic --seed 42   # generate the sample company
uv run python -m scm_ml.forecast --source synthetic      # train the forecast model
uv run python -m scm_ml.service                          # planning engine on port 8001

cd backend && ./mvnw spring-boot:run                     # backend on port 8080 (needs PostgreSQL)
cd frontend && npm ci && npm run dev                     # website on port 3000
```

The backend needs `SCM_JWT_SECRET`, and the backend and engine share `SCM_ML_INTERNAL_TOKEN` (see
[Configuration](#configuration)).

On Windows, an `&` in the folder path breaks `npm run` and the Maven wrapper in bash. Run frontend tools as
`node node_modules/<package>/...` and Maven as `.\mvnw.cmd` in PowerShell.

## Testing

```bash
bash scripts/check.sh                 # Python tests, lint and type checks
cd backend && ./mvnw verify           # Java tests (uses a real PostgreSQL in Docker)
cd frontend && npm run lint && npm run typecheck && npm test
bash scripts/e2e.sh                   # the whole flow through the real API
bash scripts/ai-regression.sh         # checks the assistant and document search didn't get worse
bash scripts/stack.sh smoke           # quick check of the running app, including the demo
```

There are over 600 tests: 402 in Python, 136 in Java and 85 for the website, plus end-to-end and smoke tests.
The CI pipeline runs all of them, builds the Docker images and scans them for known vulnerabilities
([`docs/ci.md`](docs/ci.md)).

## Re-running the benchmarks

```bash
bash scripts/benchmark.sh            # recompute every result file, then docs/benchmarks.md (about 6 minutes)
bash scripts/benchmark.sh --real     # also the real store data (downloads it once)
bash scripts/benchmark.sh --report   # only rebuild docs/benchmarks.md from the saved files
uv run python -m scm_ml.benchmark.figure                                          # the results chart
uv run python -m scm_ml.benchmark.latency --password <password>                   # speed, needs the app running
uv run python -m scm_ml.benchmark.scaling --replicas 1 2 4 --jobs 48 --repeats 3  # workers, needs kind
```

A re-run from a fresh copy of the repository reproduced every saved result; only the timings differed
([`docs/definition-of-done.md`](docs/definition-of-done.md)).

## API

| Method | Endpoint | What it does |
|---|---|---|
| POST | `/api/auth/login` | Sign in, returns a token |
| POST | `/api/auth/register` | Create a planner account and sign in |
| POST | `/api/agent/tasks` | Ask the assistant |
| POST | `/api/forecasts` | Forecast demand with a likely range |
| POST | `/api/suppliers/search` | List suppliers that can deliver, best first |
| POST | `/api/jobs` | Build a plan or run a what-if test in the background |
| POST | `/api/scenarios/{id}/runs` | Test a plan against a problem |
| POST | `/api/documents/ask` | Ask about policies and contracts |
| GET | `/api/approvals/{id}` | See an approval request and its decisions |
| POST | `/api/approvals/{id}/decision` | Approve or reject |
| POST | `/api/outcomes/demand` | Record real sales (also deliveries and stock) |
| GET | `/api/outcomes/evaluation` | Compare a decision with what really happened |
| GET | `/api/ops/summary` | System health (admin only) |

Full list: [`docs/backend-api.md`](docs/backend-api.md).

## Configuration

`scripts/stack.sh up` writes `.env` (not committed) with random passwords on first run. Everything else has a
default in `.env.example` and `application.yml`.

| Variable | What it is |
|---|---|
| `SCM_JWT_SECRET` | Key used to sign sign-in tokens (at least 32 characters, no default) |
| `SCM_ML_INTERNAL_TOKEN` | Shared password between the backend and the planning engine |
| `SCM_DEMO_PASSWORD` | Password of the four demo accounts |
| `SCM_SECURITY_ALLOWSIGNUP` | `false` turns off "Create an account" (default `true`) |
| `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database connection |
| `SCM_ML_PLANNER` | `rule` (default, works offline) or `claude` |
| `ANTHROPIC_API_KEY` | Only needed for `SCM_ML_PLANNER=claude` |
| `SCM_JOBS_WORKER_ENABLED` | Whether this backend also runs background jobs |
| `SCM_VERSION` | Docker image tag, default `local` |

## Repository layout

```text
backend/          Java backend: sign-in, permissions, approvals, jobs, database migrations
frontend/         The website
ml/src/scm_ml/    Planning engine, evaluations, benchmarks, demo
ml/experiments/   Saved results (the source of every number in this README)
src/scm_common/   Shared data definitions
infrastructure/   Dockerfiles, Kubernetes files, Terraform
scripts/          Start, stop, test and benchmark scripts
docs/             Design notes, results, demo
```

## Deployment

`compose.yaml` runs everything on one machine, and `infrastructure/kubernetes` runs it on a local Kubernetes
cluster where background workers can be scaled up. `infrastructure/terraform` describes how it would run on AWS
(ECS Fargate containers behind a load balancer, a managed PostgreSQL database, file storage, secrets, alarms).
The Terraform files pass all checks but have never been deployed to a real AWS account. The local equivalent of
each AWS piece is listed in [`docs/cloud.md`](docs/cloud.md).

## Security

You sign in with a password and get a token that lasts 8 hours by default. Anyone can create an account, but new
accounts only get the planner role; an admin gives out the approval roles. Every request checks your role
(planner, procurement manager, finance or admin). Requests are rate-limited, every change and every refused
request is written to an audit log that can't be edited, and the planning engine only accepts requests from the
backend. The ports are only open on your own machine, and the demo accounts are for local use only. Details:
[`docs/security.md`](docs/security.md).

## Limitations

- The company is made up. Real data is only used to test the forecast, and the "what really happened" data in
  the feedback loop is simulated.
- The built-in assistant combines keyword rules with matching by meaning. On sets of requests it had never
  seen, it scored between 50% and 90% (90% on the newest set of 20), so unusual wording can still confuse it.
  A Claude-based version exists but has NOT YET been measured, because no API key was used.
- On real data, the forecast is only 2.1% better than a simple 13-week average.
- The forecast's likely range is a bit too wide on the sample company: real sales fall inside it 88% of the time
  instead of 80%. A model retrained on new data was slightly worse, so it was not used.
- A plan treats the 4 weeks as one block, so it can miss timing problems inside them. On paper it covers 90.8% of
  each week's demand, but in the simulation it covered 80.3%.
- The planning engine keeps the assistant's state in one SQLite file, so it runs as a single copy; only the
  background workers scale.
- The CI pipeline has not run on GitHub yet, and the Terraform has not been deployed.

## Glossary

| Term | Meaning |
|---|---|
| SKU | A product code, for example SKU-001 |
| Likely range | The low-to-high band where actual sales should fall 80% of the time |
| Units off per week | Forecast error: how far the forecast was from real sales, on average |
| Plan builder / optimizer | The part that finds the cheapest plan meeting every limit (a mixed-integer program) |
| What-if test | Re-running a plan under a problem, such as a late or missing supplier |
| Safety buffer | Extra stock kept to cover surprises |

## Author

This is a personal project, built end to end by one person. Issues and suggestions are welcome.

| Name | Role | GitHub |
|---|---|---|
| Khoa Ho Nguyen | Author and maintainer | [@khoahonguyen0210](https://github.com/khoahonguyen0210) |

## License

MIT. See [`LICENSE`](LICENSE).
