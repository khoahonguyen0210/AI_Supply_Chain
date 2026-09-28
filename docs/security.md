# Security

## Trust boundaries

```
browser --(bearer token)--> Spring backend --(shared secret + actor)--> Python planning engine
                                  |
                                  +--> PostgreSQL
```

* The **browser** is untrusted. It holds only a short-lived access token.
* The **backend** authenticates every API call, decides what the caller's role may do, and is the
  only caller the engine accepts.
* The **engine** trusts the `actor` a request names, because only the backend can reach it: it
  rejects every call without the shared internal token.

## Authentication

* `POST /api/auth/login` (user id + password) returns a signed HS256 JWT (`sub` = user id, `role`,
  issuer `scm-backend`, expiry `scm.security.token-ttl`, 8 h by default). Everything under `/api`
  except `/api/health`, `/api/auth/login` and `/api/auth/register` needs `Authorization: Bearer <token>`;
  sessions and cookies are not used (so there is no CSRF surface).
* `POST /api/auth/register` (user id, display name, password of 12+ characters) creates an account and
  signs it in. Self sign-up always gives the `planner` role; approval roles only come from an admin
  (bootstrap users). A user id that already exists in any letter case is refused (`409 USER_ID_TAKEN`),
  sign-ups are limited per client address (`rate-limit.sign-up-per-ip`, 5 per minute), every attempt is
  audited (`SIGN_UP`), and `scm.security.allow-sign-up=false` turns it off (`403 SIGN_UP_DISABLED`).
* Passwords are stored as BCrypt hashes. A wrong password, an unknown user and a deactivated account
  produce the identical response, and an unknown user costs the same time to reject as a wrong
  password.
* Forged, tampered, expired, wrong-issuer and `alg: none` tokens are rejected (tests). A token whose
  account has been deactivated stops working on `/api/auth/me` and when the account is re-checked.
  Authorization uses the role in the token; callers cannot choose their own identity with headers.
* The frontend keeps the token in `sessionStorage` (this tab only, gone on close) and signs the user
  out when the backend answers 401. `localStorage` is not used for credentials.

## Authorization (RBAC)

Roles: `planner`, `procurement_manager`, `finance`, `admin`.

| Rule | Where it is enforced |
| --- | --- |
| `/api/ops/**` is admin only | security filter chain and the controller |
| scenarios and supplier search need a planning role | controller |
| recording outcomes (demand, deliveries, stock, forecast snapshots) needs a planning role; reading the evaluation does not | controller |
| documents are filtered by role in SQL; an unreadable document is `404` | repository |
| policy answers only use documents the role may read | engine retrieval |
| jobs, agent tasks and conversations belong to their owner (others get `404`) | service |
| who may approve a purchase order, and self-approval | engine approval policy |
| the agent can only *request* approval; no tool approves | engine |

## Abuse protection

* **Rate limits** (token buckets, per minute): login 10 per client address and 5 per user id; API
  300 per user (per address when anonymous); 30 per user for calls that start heavy work (jobs, agent
  tasks, scenario runs, questions, supplier ranking, forecasts). A refusal is `429` with
  `Retry-After`. Limits are per backend instance. They are configurable under `scm.security.rate-limit`.
* `X-Forwarded-For` is ignored unless `scm.security.trust-forwarded-for=true`. Enable it only behind a
  proxy that sets the header (the Next.js server in front of the backend does), otherwise every user
  appears to come from the proxy and shares one login limit.
* **Input validation** is at the edge of every endpoint (bean validation, typed enums, size limits)
  and again in the engine (typed contracts, tool-argument validation, numerical result checks).

## Secrets

| Secret | Variable | Rule |
| --- | --- | --- |
| JWT signing key | `SCM_JWT_SECRET` | at least 32 bytes; the backend refuses to start without it |
| backend ↔ engine token | `SCM_ML_INTERNAL_TOKEN` (both sides) | at least 16 characters; the engine refuses to start without it unless `SCM_ML_INSECURE_NO_AUTH=1` |
| first accounts | `SCM_SECURITY_BOOTSTRAPUSERS_0_USERID`, `_DISPLAYNAME`, `_ROLE`, `_PASSWORD`, ... | passwords of at least 12 characters, created or refreshed at startup |
| Claude API key | `ANTHROPIC_API_KEY` | read by the SDK only; never logged or committed |

No secret has a default value. Nothing secret is written to logs (login failures are audited without
the password).

## Audit log

`audit_log` (append-only, enforced by a trigger) records, with user, role, client address, route,
status and outcome (`SUCCESS`, `DENIED`, `FAILED`, `LIMITED`): every change (any non-GET call), every
refused request (401, 403, 429) and every login attempt. Admins read it at `GET /api/ops/audit`.
Approval decisions additionally live in the append-only `decision` table. If the audit table cannot
be written, the failure is logged and the request continues (refusing all work because auditing is
unhealthy would turn the safeguard into an outage).

## Operational endpoints

Health, metrics and Prometheus scrape (`/actuator/*`) are served on a separate management port
(`MANAGEMENT_PORT`, 8081) and are open there for probes and scrapers on a private network. Nothing is
mapped under `/actuator` on the API port. Do not publish the management port outside the cluster.

## Scanning

Dependency and container scanning run in CI (Phase 15): `pip-audit` for Python, `npm audit` for the
frontend, OWASP dependency-check for Maven, and Trivy for images and Terraform.

## Known limits

* Rate-limit state is in memory, per instance; a shared store (Redis) is the next step for many replicas.
* Tokens are not revocable before they expire except by deactivating the account (checked by
  `/api/auth/me`); keep `token-ttl` short where that matters.
* There is no password reset or account-management UI; accounts come from the bootstrap configuration.
