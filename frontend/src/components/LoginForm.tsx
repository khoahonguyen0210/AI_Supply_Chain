"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { HeroArt } from "@/components/landing/HeroArt";
import type { ArtKind } from "@/components/landing/HeroArt";
import { Notice } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/session";

/** Never hints at which part of the sign-in was wrong. */
export function loginMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "RATE_LIMITED") return error.message;
    if (error.code === "INVALID_CREDENTIALS") return "The user id or password is wrong.";
    if (error.code === "NETWORK_ERROR") return "The server cannot be reached. Try again in a moment.";
  }
  return "Sign-in failed. Try again.";
}

export function signUpMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "USER_ID_TAKEN") return "That user id is already taken. Pick another one.";
    if (error.code === "VALIDATION_FAILED") {
      const fields = new Set(error.body?.violations.map((v) => v.field) ?? []);
      if (fields.has("password")) return "Use a password of 12 to 72 characters.";
      if (fields.has("userId")) return "Use 3 to 64 letters, digits, dots, dashes or underscores for the user id.";
      return "Fill in your name, a user id and a password.";
    }
    if (error.code === "SIGN_UP_DISABLED") return "Sign-up is turned off. Ask an administrator for an account.";
    if (error.code === "RATE_LIMITED") return error.message;
    if (error.code === "NETWORK_ERROR") return "The server cannot be reached. Try again in a moment.";
  }
  return "The account could not be created. Try again.";
}

const SLIDES: { tab: string; title: string; text: string; art: ArtKind }[] = [
  {
    tab: "Forecast",
    title: "See what you will sell next.",
    text: "Weekly sales forecasts for every product.",
    art: "forecast",
  },
  {
    tab: "Suppliers",
    title: "Find the best supplier.",
    text: "Compare price, speed and reliability.",
    art: "suppliers",
  },
  {
    tab: "Plan",
    title: "Get the cheapest plan.",
    text: "What to buy, from whom, and where to send it.",
    art: "plan",
  },
  {
    tab: "Assistant",
    title: "Just ask.",
    text: "Ask in plain English. A manager approves every order.",
    art: "assistant",
  },
];

const STEPS: { title: string; text: string }[] = [
  { title: "Ask", text: "“Will we run short next month?”" },
  { title: "See the forecast", text: "How much will sell, by region." },
  { title: "Get a plan", text: "What to buy and from whom." },
  { title: "Approve", text: "Nothing is bought until a manager says yes." },
];

const RESULTS: { value: string; title: string; text: string }[] = [
  { value: "11%", title: "Better forecasts", text: "than a 13-week average" },
  { value: "13%", title: "Lower cost", text: "than the cheapest supplier" },
  { value: "100%", title: "Demand covered", text: "even if a supplier fails" },
  { value: "0", title: "Unapproved orders", text: "in 100 test requests" },
];

function ArrowCircle() {
  return (
    <svg className="arrow-circle" viewBox="0 0 44 44" aria-hidden="true" focusable="false">
      <circle cx="22" cy="22" r="20" />
      <path d="M13 22h17M24 15l7 7-7 7" />
    </svg>
  );
}

export function LoginForm() {
  const { signIn, signUp } = useAuth();
  const [slide, setSlide] = useState(0);
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [displayName, setDisplayName] = useState("");
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const signingUp = mode === "sign-up";
  const current = SLIDES[slide];

  function switchMode(next: "sign-in" | "sign-up") {
    setMode(next);
    setError(null);
    setPassword("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (signingUp) await signUp(userId, displayName, password);
      else await signIn(userId, password);
    } catch (failure) {
      setError(signingUp ? signUpMessage(failure) : loginMessage(failure));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  const ready = Boolean(userId && password && (!signingUp || displayName.trim()));

  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <div className="band-inner hero-inner" key={current.art}>
          <h1 id="hero-title" className="hero-title">
            {current.title}
          </h1>
          <p className="hero-lede">{current.text}</p>
          <a className="hero-cta" href="#sign-in" onClick={() => switchMode("sign-in")}>
            <ArrowCircle />
            Get started
          </a>
          <figure className="hero-art">
            <HeroArt kind={current.art} />
          </figure>
        </div>
      </section>

      <div className="hero-tabs-band">
        <nav className="band-inner hero-tabs" aria-label="Topics">
          {SLIDES.map((item, i) => (
            <button
              key={item.tab}
              type="button"
              className="hero-tab"
              aria-pressed={i === slide}
              onClick={() => setSlide(i)}
            >
              {item.tab}
            </button>
          ))}
          <a className="hero-tab hero-tab-last" href="#sign-in" onClick={() => switchMode("sign-in")}>
            Sign in <span aria-hidden="true">→</span>
          </a>
        </nav>
      </div>

      <section id="how" className="band band-black" aria-labelledby="how-heading">
        <div className="band-inner">
          <h2 id="how-heading" className="section-title">
            How it works
          </h2>
          <ol className="steps">
            {STEPS.map((step, i) => (
              <li key={step.title} className="step">
                <span className="step-number">{i + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="results" className="band" aria-labelledby="results-heading">
        <div className="band-inner">
          <h2 id="results-heading" className="section-title">
            Results
          </h2>
          <p className="section-note">Tested on sample data.</p>
          <dl className="results">
            {RESULTS.map((item) => (
              <div key={item.title}>
                <dt>
                  <span className="result-value">{item.value}</span>
                  <span className="result-title">{item.title}</span>
                </dt>
                <dd>{item.text}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section id="sign-in" className="band band-orange" aria-labelledby="login-heading">
        <div className="band-inner signin">
          <h2 id="login-heading" className="section-title">
            {signingUp ? "Create an account" : "Sign in"}
          </h2>
          <p className="section-note">
            {signingUp
              ? "New accounts can plan. An admin can add approval rights."
              : "Demo accounts: planner, manager, finance or admin."}
          </p>
          <form className="login-form" onSubmit={submit}>
            {signingUp ? (
              <label className="field field-wide">
                <span>Your name</span>
                <input
                  value={displayName}
                  autoComplete="name"
                  onChange={(e) => setDisplayName(e.target.value)}
                  required
                />
              </label>
            ) : null}
            <label className="field">
              <span>User id</span>
              <input value={userId} autoComplete="username" onChange={(e) => setUserId(e.target.value)} required />
            </label>
            <label className="field">
              <span>Password</span>
              <input
                type="password"
                value={password}
                autoComplete={signingUp ? "new-password" : "current-password"}
                minLength={signingUp ? 12 : undefined}
                maxLength={signingUp ? 72 : undefined}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            {signingUp ? <p className="field-hint">12 to 72 characters.</p> : null}
            <div className="login-actions">
              <button type="submit" className="primary" disabled={busy || !ready}>
                {signingUp ? (busy ? "Creating…" : "Create account") : busy ? "Signing in…" : "Sign in"}
                <span className="arrow" aria-hidden="true">
                  →
                </span>
              </button>
              <span className="switch-mode">
                {signingUp ? "Already have an account? " : "New here? "}
                <button
                  type="button"
                  className="link-button"
                  onClick={() => switchMode(signingUp ? "sign-in" : "sign-up")}
                >
                  {signingUp ? "Sign in instead" : "Create an account"}
                </button>
              </span>
            </div>
            {error ? <Notice tone="bad">{error}</Notice> : null}
          </form>
        </div>
      </section>
    </div>
  );
}
