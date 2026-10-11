import { useEffect, useState } from "react";
import { authenticate, currentUser, deleteInvestigation, getHistory, getInvestigation, health, logout, setAccessToken, type AuthReply } from "./api";
import type { Health, Investigation } from "./types";
import Upload from "./components/Upload";
import Result from "./components/Result";
import { Btn, Card } from "./components/ui";

type View = "home" | "result" | "history" | "how" | "about" | "settings";
interface Saved { id: string; kind: string; at: string; assessment: string; fileName?: string; modelStatus?: string; modelScore?: string }
const KEY = (userId: string) => `satyam.history.${userId}`;
const load = (userId: string): Saved[] => { try { return JSON.parse(localStorage.getItem(KEY(userId)) ?? "[]"); } catch { return []; } };
const NAV: [View, string][] = [["how", "How it works"], ["history", "Past checks"], ["settings", "Privacy"]];
const getModelOutput = (modules: Investigation["modules"]) => modules.find((module) => ["ai_model", "audio_model"].includes(module.id));
const getModelStatus = (modules: Investigation["modules"]) => modules.find((module) => ["ai_model", "audio_model", "video_frames", "video_audio"].includes(module.id))?.status;
interface SignedIn { user_id: string; username: string }

function savedSession(): SignedIn | null {
  try {
    const value = sessionStorage.getItem("satyam.session");
    const token = sessionStorage.getItem("satyam.access-token");
    return value && token ? JSON.parse(value) as SignedIn : null;
  } catch { return null; }
}

function AuthGate({ onAuthenticated }: { onAuthenticated: (user: SignedIn, reply: AuthReply) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setWorking(true); setError("");
    try {
      const reply = await authenticate(mode, username, password);
      onAuthenticated({ user_id: reply.user_id, username: reply.username }, reply);
    } catch (reason) { setError((reason as Error).message); }
    finally { setWorking(false); }
  }
  return <div className="app-shell"><main className="subpage">
    <section className="landing-hero"><p className="hero-tagline">PRIVATE MEDIA CHECKS</p><h1>Sign in to SATYAM AI</h1>
      <p>Create an account or sign in to access your private uploads and analysis history.</p></section>
    <Card><form className="grid gap-4" onSubmit={(event) => void submit(event)}>
      <div className="media-kind-tabs" role="tablist" aria-label="Authentication mode">
        {(["login", "register"] as const).map((choice) => <button key={choice} type="button" role="tab"
          aria-selected={mode === choice} className={mode === choice ? "active" : ""}
          onClick={() => { setMode(choice); setError(""); }}>{choice === "login" ? "Sign in" : "Create account"}</button>)}
      </div>
      <label className="grid gap-1 text-sm">Username<input className="rounded-xl bg-ground p-3 text-ink" minLength={3} maxLength={32}
        autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} /></label>
      <label className="grid gap-1 text-sm">Password<input className="rounded-xl bg-ground p-3 text-ink"
        type="password" minLength={mode === "register" ? 12 : 1} maxLength={256}
        autoComplete={mode === "register" ? "new-password" : "current-password"} required
        value={password} onChange={(event) => setPassword(event.target.value)} />
        {mode === "register" && <span className="text-xs text-muted">Use at least 12 characters.</span>}</label>
      <button disabled={working} className="rounded-xl bg-violet px-5 py-3 font-bold text-white disabled:opacity-50">
        {working ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
      </button>
      {error && <p role="alert" className="rounded-xl bg-[#FFE4DF] p-3 text-sm font-bold text-[#7A1B0C]">{error}</p>}
    </form></Card>
    <p className="text-center text-xs text-muted">Passwords are hashed on the backend. Use HTTPS when deploying beyond localhost.</p>
  </main></div>;
}

export default function App() {
  const [session, setSession] = useState<SignedIn | null>(savedSession);
  const [view, setView] = useState<View>("home");
  const [inv, setInv] = useState<Investigation | null>(null);
  const [media, setMedia] = useState<string | undefined>();
  const [hist, setHist] = useState<Saved[]>(() => session ? load(session.user_id) : []);
  const [h, setH] = useState<Health | null>(null);
  const [hErr, setHErr] = useState(false);
  useEffect(() => { health().then(setH).catch(() => setHErr(true)); }, []);
  useEffect(() => {
    if (!session) return;
    currentUser().catch(() => clearSession());
  }, []);
  useEffect(() => {
    if (!session) return;
    let active = true;
    getHistory().then((items) => {
      const prior = load(session.user_id);
      const saved = items.map((item) => ({
        id: item.id,
        kind: item.kind,
        at: item.created_at,
        assessment: item.fusion.assessment,
        fileName: prior.find((entry) => entry.id === item.id)?.fileName,
        modelStatus: getModelStatus(item.modules),
        modelScore: getModelOutput(item.modules)?.score ? JSON.stringify(getModelOutput(item.modules)?.score) : undefined,
      }));
      if (!active) return;
      setHist(saved);
      localStorage.setItem(KEY(session.user_id), JSON.stringify(saved));
    }).catch((reason: unknown) => {
      if (!active) return;
      setHErr(true);
      if (reason instanceof Error && reason.message === "Sign in to continue.") clearSession();
    });
    return () => { active = false; };
  }, [session?.user_id]);
  useEffect(() => () => { if (media) URL.revokeObjectURL(media); }, [media]);
  const persist = (x: Saved[]) => {
    setHist(x);
    if (session) localStorage.setItem(KEY(session.user_id), JSON.stringify(x));
  };

  function signIn(user: SignedIn, reply: AuthReply) {
    setAccessToken(reply.access_token);
    sessionStorage.setItem("satyam.session", JSON.stringify(user));
    setSession(user); setHist(load(user.user_id)); setHErr(false);
  }

  function clearSession() {
    setAccessToken("");
    sessionStorage.removeItem("satyam.session");
    setSession(null); setHist([]); setInv(null); setMedia(undefined); setView("home");
  }

  async function signOut() {
    try { await logout(); } catch { /* Clear the local session even if it already expired. */ }
    clearSession();
  }

  function done(i: Investigation, file: File, mediaUrl: string) {
    setInv(i); setMedia(mediaUrl); setView("result");
    const model = getModelOutput(i.modules);
    persist([{ id: i.id, kind: i.kind, at: i.created_at, assessment: i.fusion.assessment, fileName: file.name,
      modelStatus: getModelStatus(i.modules), modelScore: model?.score ? JSON.stringify(model.score) : undefined }, ...hist].slice(0, 50));
  }
  async function open(id: string) {
    try { setInv(await getInvestigation(id)); setMedia(undefined); setView("result"); }
    catch { persist(hist.filter((x) => x.id !== id)); alert("That investigation no longer exists."); }
  }
  const gone = () => { if (inv) persist(hist.filter((x) => x.id !== inv.id)); setInv(null); setView("home"); };
  const startCheck = () => {
    setView("home");
    requestAnimationFrame(() => document.getElementById("upload")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  };

  if (!session) return <AuthGate onAuthenticated={signIn} />;

  if (view === "result" && inv) {
    return <main className="app-shell result-shell"><Result inv={inv} mediaUrl={media} onBack={() => setView("home")} onDeleted={gone} /></main>;
  }

  return (
    <div className="app-shell">
      <a href="#main" className="sr-only focus:not-sr-only">Skip to content</a>
      <header className="site-header">
        <button onClick={() => setView("home")} className="brand" aria-label="SATYAM AI home">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></svg>
          <span>satyam<span className="brand-accent">.ai</span></span>
        </button>
        <nav aria-label="Main navigation" className="site-nav">
          {NAV.map(([v, label]) => <button key={v} onClick={() => setView(v)} aria-current={view === v ? "page" : undefined}>{label}</button>)}
        </nav>
        <div className="flex items-center justify-end gap-3"><span className="text-xs text-muted">{session.username}</span>
          <button className="start-check" onClick={startCheck}>Start a check</button>
          <button className="text-xs text-muted underline" onClick={() => void signOut()}>Sign out</button></div>
      </header>
      <main id="main">
        {view === "home" && <>
          <section className="landing-hero">
            <p className="hero-tagline">TRUTH BEYOND PIXELS</p>
            <h1>Don't just watch it.<br />Verify it.</h1>
            <p>Got a photo or video that feels off? Drop it in. We look at it from several angles and show you the evidence, including what we couldn't check.</p>
          </section>
          {hErr && <p role="alert" className="service-alert">The backend is not reachable. Double-click start-backend.bat in the project folder, keep its window open, then reload.</p>}
          <section id="upload" className="upload-stage" aria-label="Upload media">
            <aside className="signal-note signal-note-left"><b>Evidence over certainty</b><span>Multiple clues help; no single check is a definitive verdict.</span></aside>
            <Upload onDone={done} userId={session.user_id} health={h} />
            <aside className="signal-note signal-note-right"><b>Transparent results</b><span>Each result explains what was checked and what was not.</span></aside>
          </section>
          <section className="feature-grid" aria-label="Our approach">
            {[["Explainable evidence", "Every finding says what it means and what innocent thing could cause it."], ["Image, video and audio", "Each format uses its own checks. Unsupported model capabilities stay unavailable."], ["Transparent confidence", "Raw scores stay labelled as raw scores. Unavailable checks stay unavailable."]].map(([title, desc], i) => (
              <Card key={title} className="feature-card"><div className="feature-number">{i + 1}</div><h2>{title}</h2><p>{desc}</p></Card>
            ))}
          </section>
          <p className="landing-disclaimer">AI detection is probabilistic. We can't guarantee any file is real or fake, so treat results as clues to follow up.</p>
        </>}
        {view === "history" && <section className="subpage"><h1>Past checks</h1>
          {hist.length === 0 ? <Card><p className="text-muted">No investigations yet. They appear here on this device after your first check.</p></Card> :
            <div className="history-list">{hist.map((s) => (<Card key={s.id} className="history-card">
              <div><b>{s.fileName ?? <span className="capitalize">{s.kind}</span>}</b> · {s.assessment.replace(/_/g, " ")}
                <div className="text-xs text-muted">{new Date(s.at).toLocaleString()} · {s.id.slice(0, 8)} · Model: {s.modelStatus ?? "not run"}</div>
                {s.modelScore && <div className="text-xs text-muted">Raw model score: {s.modelScore.slice(0, 100)}</div>}</div>
              <div className="flex gap-2"><Btn kind="ghost" onClick={() => open(s.id)}>Open</Btn><Btn kind="ghost" onClick={async () => { await deleteInvestigation(s.id); persist(hist.filter((x) => x.id !== s.id)); }}>Delete</Btn></div>
            </Card>))}</div>}</section>}
        {view === "how" && <section className="subpage"><h1>How it works</h1>
          {[["1. Validate", "We check the real file signature, size and duration, not just the file name."], ["2. Hash", "A SHA-256 fingerprint identifies exactly which file was examined."], ["3. Examine", "Metadata, a recompression test (JPEG), an optional AI-image model, and sampled video frames."], ["4. Fuse", "Simple, published rules combine the findings. Disagreements are shown, never hidden."], ["5. Explain", "You get plain-language findings, limitations and next steps."]].map(([title, desc]) => <Card key={title}><b>{title}</b><p className="text-sm text-muted">{desc}</p></Card>)}</section>}
        {view === "about" && <section className="subpage"><h1>About the technology</h1>
          <Card><p className="text-sm text-muted">Frontend: React, TypeScript, Vite, Tailwind. Backend: FastAPI, Pillow, OpenCV, SQLite. The AI module is an adapter around a pretrained Hugging Face image classifier that you choose; it is optional and reported as unavailable when not configured. The fusion rules are heuristic and uncalibrated, so no probability is claimed. Audio-visual checks and region overlays are not implemented.</p></Card></section>}
        {view === "settings" && <section className="subpage"><h1>Privacy</h1>
          <Card><h2 className="font-bold">Backend status</h2>{h ? <ul className="mt-2 text-sm text-muted">{Object.entries(h.modules).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul> : <p className="text-sm text-muted">{hErr ? "Unreachable." : "Checking..."}</p>}</Card>
          <Card><h2 className="font-bold">Retention</h2><p className="text-sm text-muted">Original media: deleted immediately after processing. Results: kept on the server until you delete them. This device remembers only investigation IDs.</p>
            <div className="mt-3"><Btn kind="ghost" onClick={async () => { if (confirm("Delete all investigations from the server and this device?")) { await Promise.all(hist.map((s) => deleteInvestigation(s.id))); persist([]); } }}>Delete all my investigations</Btn></div>
            <button className="text-link mt-4" onClick={() => setView("about")}>About the technology</button></Card></section>}
      </main>
    </div>
  );
}
