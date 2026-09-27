# Frontend

Next.js (App Router) on port 3000. The browser talks only to its own origin; `/api/*` is proxied to
the Spring backend (`next.config.ts`, `BACKEND_URL`). The UI renders what the backend returns and never
recomputes planning results; the few comparisons it makes (for example "below safety stock") are
display-only.

## Pages

| Route | Purpose |
| --- | --- |
| `/` Planner dashboard | one product: weekly demand and its forecast with the 80% interval, inventory per warehouse, ranked supplier options for a chosen warehouse and quantity, recent recommendations, saved scenarios |
| `/workspace` Decision workspace | build a purchase plan (optimization job) and inspect its assumptions, constraints closest to binding, purchase lines and per-line supplier alternatives; stress it with a disruption (scenario job) and read baseline / disrupted / re-planned differences; ask the policy documents a question and see the citations |
| `/workspace/[id]` | one recommendation: summary, assumptions, evidence, lines, approval progress and decisions |
| `/copilot` | conversation with the agent: answer, status, assumptions, citations, a one-line-per-action trace (arguments one click deeper), guardrail findings in plain words, links to the recommendation and approval |
| `/approvals` | the approval queue and the decision form (approve or reject with a rationale) |
| `/documents` | documents the signed-in role may read, with version validity |
| `/status` | backend health |

## Behaviour worth knowing

* **Identity.** Until token authentication (Phase 11) the header's "Signed in as" menu picks one of four
  dev users (planner, procurement manager, finance, admin). The choice is sent as `X-User-Id` /
  `X-User-Role` on every request and kept in `localStorage`. Pages wait for the stored choice before
  fetching, and refetch when the user changes.
* **Jobs.** Optimization and scenarios are submitted as jobs with a fresh `Idempotency-Key`, polled
  with progress ("Queued…", "Running (attempt 1 of 3)…"), and a failed job shows the engine's own
  message. Leaving the page stops polling.
* **Honest uncertainty.** Prediction intervals exist per region only; the all-regions chart shows the
  summed point forecast with no band and says why.
* **Approvals.** The UI offers the decision form on any pending approval; whether the signed-in role may
  decide is the engine's rule, and its refusal reason is shown. Nothing is ordered until the policy's
  approvers have approved.
* **Accessibility.** Charts have a text summary (`role="img"` with a label), forms use labelled fields,
  status never relies on colour alone (badges carry text), and animations are switched off under
  `prefers-reduced-motion`.
* **Look.** One dark theme, defined as CSS variables at the top of `src/app/globals.css`: a near-black
  canvas with a soft radial glow and a faint dot grid, Ubuntu for headings, Manrope for text, Geist Mono
  for ids, white primary buttons beside outlined ones, rounded thin-bordered cards with hover states, and
  a staggered fade-in when a page loads. Signed out, the sign-in form sits in a landing hero with an
  example recommendation (numbers from the demo run of the synthetic company) and four feature cards.
  Text is kept short: one-line page intros, and a long copilot answer shows its first line and its
  conclusion, with the rest folded under "Show the full answer".

## Tests and checks

`node node_modules/vitest/vitest.mjs run` (64 tests: API client, job polling, data shaping, every page
with a stubbed backend), `node node_modules/typescript/bin/tsc --noEmit`,
`node node_modules/eslint/bin/eslint.js`, `node node_modules/next/dist/bin/next build`. On Windows the
`&` in the repository folder name breaks the `npm run` shims, hence the direct `node` calls.
