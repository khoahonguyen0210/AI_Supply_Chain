# Local Kubernetes (kind)

## Commands

```bash
bash scripts/kind.sh up        # build images, create cluster `scm`, load images, apply, wait for rollout + seed
bash scripts/kind.sh smoke     # tests/smoke through the cluster's frontend (http://localhost:8300)
bash scripts/kind.sh scale 4   # worker pods (each with its own engine)
bash scripts/kind.sh status
bash scripts/kind.sh down      # delete the cluster
```

Needs Docker, kubectl and bash. `kind` is used from PATH, else downloaded once into `.tools/` (git-ignored) and its
SHA-256 checked against the release. Secrets are generated into `infrastructure/kubernetes/secrets.env` (git-ignored)
and turned into the `scm-secrets` Secret by kustomize. Ports: frontend http://localhost:8300, API
http://localhost:8380 (NodePorts mapped to localhost only).

## Layout (`infrastructure/kubernetes/`, namespace `scm`)

| Workload | Kind | Replicas | Notes |
|---|---|---|---|
| `postgres` | StatefulSet + PVC | 1 | pgvector PostgreSQL 16 |
| `backend` | Deployment, NodePort 30380 | 1 | API only (`SCM_JOBS_WORKER_ENABLED=false`); talks to `engine` |
| `worker` | Deployment | scalable | one pod = queue worker (backend image, worker on) + its own engine as a native sidecar on localhost, 1 CPU, thread pools pinned to 1 |
| `engine` | Deployment (Recreate) + PVC | exactly 1 | stateful engine: agent tasks, approvals and decisions in SQLite on its volume |
| `seed` | Job | - | idempotent seed once the schema exists |
| `frontend` | Deployment, NodePort 30300 | 1 | proxies `/api/*` to the `backend` Service |

Why the engine appears twice: it keeps approval state in a local SQLite file, so replicas behind one Service would
each see a different set of approvals; the API's engine therefore runs as exactly one pod. Queued work (optimisation,
scenarios, forecasts) is stateless, so every worker pod carries its own engine as a sidecar and the pod is the
scaling unit. A first version used a separate `engine-compute` Deployment behind a Service; at 4 replicas the
per-job run time doubled because each worker keeps one keep-alive connection and kube-proxy balances per connection,
so several workers could land on the same 1-CPU engine while another idled. The sidecar removes that by
construction. Batch agent evaluations sent through the queue record their agent runs in the sidecar's scratch state,
not in the main engine; their results are still stored durably in the job row. Moving the engine's state into
PostgreSQL would remove the split; it is listed as a limitation, not done.

CPU: the engine's native libraries (LightGBM/OpenMP, BLAS) size their thread pools to the node's cores (16 here) by
default; with several engines on one node that oversubscribes the CPU (measured: 81 threads per engine). The worker's
engine is limited to 1 CPU with `OMP_NUM_THREADS=1` (and the BLAS equivalents).

Probes: Spring's liveness/readiness groups on the management port, the engine's `/health`, `pg_isready`; init
containers wait for the backend so the schema exists before the engine syncs the knowledge base. Every pod sets
`enableServiceLinks: false`: otherwise the `backend` Service injects `BACKEND_PORT=tcp://...`, which collides with the
backend's own `BACKEND_PORT` setting and stops it from starting (found while bringing the cluster up).

Local-cluster-only settings, called out in the manifests: the per-user limit on expensive calls is raised to 1000/min so
one benchmark user can enqueue a batch (default 30/min), and the worker lease is 120 s (default 300 s) so a crashed
worker's job is taken over within the benchmark window. Jobs in the benchmark take seconds; a lease shorter than the
longest job would let a second worker start the same job.

## Scaling demonstration (Task 14.2)

```bash
bash scripts/kind.sh up
uv run python -m scm_ml.benchmark.scaling --replicas 1 2 4 --jobs 48 --repeats 3 --disrupt
```

Workload: 48 optimisation jobs (4 SKUs, 8-week horizon, demand multiplier 1.0-1.4; `scm_ml.benchmark.workers.workload`),
submitted in one burst through the public API by one planner. Timings come from the jobs' own `createdAt` /
`startedAt` / `finishedAt`, not from client polling. Two unrecorded warm-up jobs per worker after each scale. One
kind node, 16 CPUs; each worker pod gets 1 CPU for its engine. Artifact:
[`ml/experiments/systems/worker-scaling.json`](../ml/experiments/systems/worker-scaling.json) (revision `a0c3686`).

| Workers | Makespan, median of 3 (s) | Throughput, median (jobs/min) | Throughput range (jobs/min) | Job run time p50 (s) | Failed |
|---|---|---|---|---|---|
| 1 | 89.9 | 32.0 | 31.6 - 47.9 | 1.62 | 0/144 |
| 2 | 36.4 | 79.1 | 62.8 - 81.7 | 1.30 | 0/144 |
| 4 | 28.9 | 99.6 | 96.3 - 119.7 | 1.88 | 0/144 |

* 1 to 4 workers: median throughput 3.1x, median makespan down 68%. Scaling is sub-linear from 2 to 4 workers: the
  per-job run time rises (p50 1.30 s to 1.88 s) as four engines, the API, the worker JVMs and PostgreSQL share one
  node, and a 48-job batch leaves a fixed tail (submission, the last jobs) that more workers do not shorten.
* Variance: one of the three single-worker runs was much faster (60.2 s vs about 90 s). The runs were sequential on a
  laptop, so the medians are reported and the full spread is in the artifact.

**Failure behaviour** (`--disrupt`, 4 workers): 8 s after submission one worker pod was force-deleted
(`--grace-period=0 --force`, as a crash). All 48 jobs succeeded, none failed, none was left unfinished; 5 jobs needed a
second attempt. The killed pod's engine went down with it, its in-flight calls failed, and the worker's retry path
(5xx or connection error with attempts left) put them back on the queue for the remaining workers, so nothing waited
for the 120 s lease. Makespan was 39.3 s against 24.1-29.9 s undisrupted (73.2 jobs/min).

Not measured here: more than 4 workers (the single node is the limit), a multi-node cluster, and a worker killed while
its engine stays up (that case is covered by the lease takeover, tested in `JobQueueTest` rather than here).
