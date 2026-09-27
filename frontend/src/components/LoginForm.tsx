"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Notice } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/session";

/** What to tell the person who could not sign in, without hinting at which part was wrong. */
export function loginMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "RATE_LIMITED") return error.message;
    if (error.code === "INVALID_CREDENTIALS") return "The user id or password is wrong.";
    if (error.code === "NETWORK_ERROR") return "The server cannot be reached. Try again in a moment.";
  }
  return "Sign-in failed. Try again.";
}

const STEPS: { title: string; text: string }[] = [
  {
    title: "Ask a question",
    text: "Type it the way you would say it, for example “Demand for SKU-001 may rise 20%. What should I do?”",
  },
  {
    title: "See the forecast",
    text: "How much you will likely sell in each region over the next weeks, with a low-to-high range.",
  },
  {
    title: "Get a purchase plan",
    text: "Which suppliers to buy from, how much, and for which warehouse, at the lowest total cost.",
  },
  {
    title: "Approve it",
    text: "A manager reviews the plan. Nothing is bought until the right people approve it.",
  },
];

const FEATURES: { title: string; text: string; icon: string }[] = [
  {
    title: "Predict demand",
    text: "Expected sales for each product and region, week by week.",
    icon: "M3 17l5-6 4 3 6-8 3 3",
  },
  {
    title: "Compare suppliers",
    text: "Price, delivery time and on-time record, side by side.",
    icon: "M4 6h16M4 12h10M4 18h6",
  },
  {
    title: "Prepare for problems",
    text: "See what happens if a supplier stops delivering or demand jumps, and how to adjust.",
    icon: "M12 4l9 16H3zM12 10v4M12 17v.5",
  },
  {
    title: "Check the rules",
    text: "Ask about policies and contracts and get the answer with its exact source.",
    icon: "M6 3h9l4 4v14H6zM9 12h7M9 16h7",
  },
];

export function LoginForm() {
  const { signIn } = useAuth();
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(userId, password);
    } catch (failure) {
      setError(loginMessage(failure));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="landing">
      <section className="hero">
        <div className="hero-copy">
          <h1 className="hero-title">
            Plan what to buy <span className="gradient-text">before you run short.</span>
          </h1>
          <p className="hero-lede">
            See how much you will likely sell, compare suppliers, and get a purchase plan your manager can
            approve. Every number shows where it came from.
          </p>

          <section id="sign-in" className="login-card" aria-labelledby="login-heading">
            <h2 id="login-heading">Sign in</h2>
            <form className="login-form" onSubmit={submit}>
              <label className="field">
                <span>User id</span>
                <input
                  value={userId}
                  autoComplete="username"
                  onChange={(e) => setUserId(e.target.value)}
                  required
                />
              </label>
              <label className="field">
                <span>Password</span>
                <input
                  type="password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </label>
              <div className="login-actions">
                <button type="submit" className="primary" disabled={busy || !userId || !password}>
                  {busy ? "Signing in…" : "Sign in"}
                  <span className="arrow" aria-hidden="true">
                    →
                  </span>
                </button>
                <a className="button-outline" href="#how">
                  How it works
                </a>
              </div>
              {error ? <Notice tone="bad">{error}</Notice> : null}
            </form>
          </section>
        </div>

        <figure className="hero-visual" aria-hidden="true">
          <div className="preview">
            <div className="preview-head">
              <span className="preview-dot" />
              <span>Proposed order · SKU-001</span>
              <span className="preview-badge">Waiting for approval</span>
            </div>
            <svg className="preview-chart" viewBox="0 0 320 120" preserveAspectRatio="none">
              <defs>
                <linearGradient id="preview-line" x1="0" x2="1">
                  <stop offset="0%" stopColor="#a78bfa" />
                  <stop offset="100%" stopColor="#38bdf8" />
                </linearGradient>
              </defs>
              <path className="preview-band" d="M200,70 L320,40 L320,95 L200,92 Z" />
              <path
                className="preview-history"
                d="M0,90 L20,60 L40,82 L60,48 L80,66 L100,58 L120,80 L140,52 L160,62 L180,44 L200,78"
              />
              <path className="preview-forecast" d="M200,78 L230,70 L260,64 L290,58 L320,52" />
            </svg>
            <div className="preview-legend">
              <span className="legend-past">Past sales</span>
              <span className="legend-next">Forecast and likely range</span>
            </div>
            <dl className="preview-stats">
              <div>
                <dt>Sales, next 4 weeks</dt>
                <dd>1,070</dd>
              </div>
              <div>
                <dt>Total cost</dt>
                <dd>$78.6k</dd>
              </div>
              <div>
                <dt>Demand covered</dt>
                <dd>100%</dd>
              </div>
            </dl>
            <ul className="preview-lines">
              <li>
                <span>Buy from SUP-008 for 3 warehouses</span>
                <span>657 units</span>
              </li>
              <li>
                <span>Buy from SUP-003 for WH-3</span>
                <span>283 units</span>
              </li>
              <li>
                <span>Extra cost if SUP-008 stops delivering</span>
                <span>+$957</span>
              </li>
            </ul>
          </div>
          <figcaption>Example with sample data</figcaption>
        </figure>
      </section>

      <section id="how" className="section" aria-labelledby="how-heading">
        <h2 id="how-heading" className="section-title">
          How it works
        </h2>
        <ol className="steps">
          {STEPS.map((step, i) => (
            <li key={step.title} className="step-card">
              <span className="step-number">{i + 1}</span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section id="features" className="section" aria-labelledby="features-heading">
        <h2 id="features-heading" className="section-title">
          What you can do
        </h2>
        <div className="feature-grid">
          {FEATURES.map((feature) => (
            <article key={feature.title} className="feature-card">
              <div className="feature-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d={feature.icon} />
                </svg>
              </div>
              <div>
                <h3>{feature.title}</h3>
                <p className="feature-text">{feature.text}</p>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
