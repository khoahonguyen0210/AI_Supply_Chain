# CI/CD

Two GitHub Actions workflows, both free to run (GitHub-hosted runners, no API keys, no cloud account).

## `CI` (`.github/workflows/ci.yml`)

Runs on pull requests, pushes to `main` and `v*` tags.

| Job | What it runs | Needs |
|---|---|---|
| `python` | `ruff check`, `ruff format --check`, `mypy` (strict), `pytest` (pgvector tests included, Docker is on the runner) | - |
| `java` | `./mvnw verify`: unit and Testcontainers integration tests, then the jar (uploaded for 14 days) | - |
| `frontend` | `npm ci`, eslint, `tsc --noEmit`, vitest, `next build` | - |
| `e2e` | trains the synthetic forecast model, then `scripts/e2e.sh` (PostgreSQL + backend jar + engine, driven through the public API) | python, java |
| `dependencies` | `pip-audit` on the locked runtime dependencies (hash-checked), `npm audit --omit=dev --audit-level=high` | - |
| `images` | `scripts/stack.sh up` (builds the three images, starts the Compose stack, waits for health), `scripts/stack.sh smoke`, Trivy scan of each image, then on a push: tag and push to GHCR | python, java, frontend |

The AI regression gate is a separate workflow (`ai-regression.yml`, [testing.md](testing.md)) because it only depends
on the Python sources.

## Versioned images (Task 15.2)

The `images` job builds `scm-backend`, `scm-ml` and `scm-frontend` once, tests that exact build with the smoke test and
the scan, and only then pushes it to `ghcr.io/<owner>/<image>`:

| Trigger | Tags |
|---|---|
| push to `main` | `sha-<7-char commit>`, `main` |
| tag `vX.Y.Z` | `sha-<7-char commit>`, `X.Y.Z`, `latest` |
| pull request | built and tested, not pushed |

Pushing uses the workflow's own `GITHUB_TOKEN` (`packages: write` on that job only), so no registry secret is
configured. Locally the same images are built by `docker compose build` with the tag `SCM_VERSION` (default `local`).

## Security scanning

* Python: `pip-audit --strict --require-hashes` on `uv export --no-dev` (exactly what the images install).
* Frontend: `npm audit` on runtime dependencies, failing on high or critical.
* Images: Trivy 0.74.0 (the `aquasec/trivy` image pinned by digest, run with `docker run`; not
  `aquasecurity/trivy-action`, whose tags were force-pushed to malicious commits in March 2026, CVE-2026-33634) fails
  the build on CRITICAL or HIGH vulnerabilities that have a fix. It covers the OS packages and the libraries inside each
  image, including the backend jar's Java dependencies. OWASP dependency-check was the original plan for Java; without
  an NVD API key its database download takes most of an hour per run, and the image scan covers the same jars.

Findings fixed when the scan was introduced (2026-10-07):

| Image | Finding | Fix |
|---|---|---|
| `scm-backend` | 3 CRITICAL in `tomcat-embed-core` 11.0.24, 5 HIGH in Jackson 3 `jackson-core`/`jackson-databind` 3.1.5, all managed by Spring Boot 4.1.1 | `backend/pom.xml` overrides `tomcat.version` (11.0.25) and `jackson-bom.version` (3.1.7); drop them once the Boot parent manages these versions or newer |
| `scm-frontend` | 7 HIGH (brace-expansion, ip-address, tar, undici), all inside the npm CLI bundled with `node:24-alpine` | the runtime stage deletes npm, npx and corepack; the server runs as `node server.js` and never uses them |

A finding without a fix, or below HIGH, does not fail the build. To accept one deliberately, add its ID to a
`.trivyignore` file at the repository root with a comment saying why.

## Verified locally

The remote has not been set up (the repository is local only), so the workflows have not run on GitHub yet. What was
checked on this machine:

* `actionlint` 1.7.7 (with shellcheck) reports no problems in either workflow.
* Every job's commands pass locally: `scripts/check.sh`, `mvnw verify` (124 tests), the frontend
  lint/typecheck/test, the three image builds (the frontend image runs `next build`), `scripts/e2e.sh`, and the stack
  smoke test (`tests/smoke`, also run against the kind cluster).
* `pip-audit` and `npm audit` as configured: no known vulnerabilities (2026-10-07).
* Trivy as configured on the three local images: no fixable CRITICAL or HIGH finding (2026-10-07).

To run it on GitHub: create an empty repository, `git remote add origin <url>`, `git push -u origin main --tags`.
