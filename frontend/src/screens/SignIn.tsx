// Sign in: a centred card on a dot field. Accounts only; there is no sign-up.
import { useState } from "react";
import { api, errorText } from "../api";
import { Arrow, Mark } from "../components/bits";

const dots = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14'%3E%3Crect x='4' y='4' width='5' height='5' fill='%231C1C1A'/%3E%3C/svg%3E")`;

export function SignIn({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await api.login(email, password); onDone(); }
    catch (err) { setError(errorText(err)); setBusy(false); }
  };

  return (
    <main className="signin" style={{ backgroundImage: dots }}>
      <form onSubmit={submit} aria-labelledby="signin-h">
        <div className="brand"><Mark /><span>TRACE</span></div>
        <div className="stack gap8">
          <h1 id="signin-h" style={{ fontSize: 28 }}>Sign in</h1>
          <p className="muted">For accountable investigation and footage verification. Every upload, search and export is logged to your account.</p>
        </div>
        <label className="field"><span className="mono11">Email</span>
          <input className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field"><span className="mono11">Password</span>
          <input className={`input${error ? " invalid" : ""}`} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div className="error-line" role="alert">{error}</div>}
        <button type="submit" className={`pill primary${busy ? " busy" : ""}`} disabled={busy}>
          {busy ? "Signing in" : <><span>Sign in</span><Arrow /></>}
        </button>
      </form>
    </main>
  );
}
