import { useState, type FormEvent } from "react";
import WsuLogo from "./WsuLogo";

type TokenGateProps = {
  error: string | null;
  checking: boolean;
  onSubmit: (token: string) => void;
};

/** Sign in with the admin token configured on the API server (AWN_ADMIN_TOKEN). */
export default function TokenGate({ error, checking, onSubmit }: TokenGateProps) {
  const [token, setToken] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token.trim()) onSubmit(token.trim());
  }

  return (
    <main className="gate">
      <form className="card gate-card" onSubmit={handleSubmit}>
        <div className="gate-mark">
          <WsuLogo />
        </div>
        <h1>AgWeatherNet admin</h1>
        <p className="card-subtitle">Sign in to view LLM cost, usage, and performance.</p>
        <label htmlFor="admin-token">Admin token</label>
        <input
          id="admin-token"
          type="password"
          autoComplete="current-password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "admin-token-error" : undefined}
          required
        />
        {error && (
          <p id="admin-token-error" className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="primary-button" disabled={checking}>
          {checking ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
