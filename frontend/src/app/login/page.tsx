"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";

const DEMO_ACCOUNTS = [
  { email: "admin@dmp.com", role: "Admin" },
  { email: "operator@dmp.com", role: "Operator" },
  { email: "ai@dmp.com", role: "AI Engineer" },
];

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { signIn } = useAuth();
  const [email, setEmail] = useState(DEMO_ACCOUNTS[0].email);
  const [password, setPassword] = useState("demo123");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const nextPath = useMemo(() => {
    const next = searchParams.get("next");
    return next?.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
  }, [searchParams]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      await signIn({ email, password });
      router.replace(nextPath);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-brand">
          <span className="sb-logo">
            <Icon name="bolt" />
          </span>
          <div>
            <h1 id="login-title">Data Platform</h1>
            <p>Sign in to Energy Management</p>
          </div>
        </div>

        <form className="login-form" onSubmit={onSubmit}>
          <label className="field">
            <span>Email</span>
            <input className="input" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>

          <label className="field">
            <span>Password</span>
            <input className="input" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>

          {error && <div className="login-error">{error}</div>}

          <button className="btn btn-primary login-submit" type="submit" disabled={submitting}>
            {submitting ? <Icon name="refresh" className="spin" /> : <Icon name="shield" />}
            <span>{submitting ? "Signing in..." : "Sign in"}</span>
          </button>
        </form>

        <div className="demo-accounts">
          {DEMO_ACCOUNTS.map((account) => (
            <button key={account.email} type="button" className={account.email === email ? "is-selected" : ""} onClick={() => setEmail(account.email)}>
              <span>{account.role}</span>
              <b>{account.email}</b>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}
