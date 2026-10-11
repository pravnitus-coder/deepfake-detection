import { useRef, useState } from "react";
import { deleteInvestigation, downloadReport } from "../api";
import type { Investigation } from "../types";
import { Btn, Card, Chip } from "./ui";
import ScoreChart from "./ScoreChart";

const HEAD = { likely_manipulated: "This may be AI-generated or manipulated.", no_strong_evidence: "No strong signs of manipulation found.", inconclusive: "We're not sure. Here's why." } as const;
const POS: Record<string, number | null> = { LOW: 12, MODERATE: 50, HIGH: 88, UNDETERMINED: null };

export default function Result({ inv, mediaUrl, onBack, onDeleted }: { inv: Investigation; mediaUrl?: string; onBack: () => void; onDeleted: () => void }) {
  const vid = useRef<HTMLVideoElement>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [claim, setClaim] = useState("");
  const [asked, setAsked] = useState(false);
  const f = inv.fusion, pos = POS[f.risk_indicator];
  const model = inv.modules.find((m) => m.id === "ai_model" || m.id === "audio_model" || m.id === "video_frames");
  const evaluatedFrames = inv.frames.filter((frame) => frame.model_status === "completed");
  const flaggedFrames = evaluatedFrames.filter((frame) => frame.stance === "supports_manipulation").length;
  const checks = ["Find the original publisher", "Run a reverse-image search", "Compare with credible reporting"];
  return (
    <div className="result-page">
      <div className="result-toolbar">
        <button className="text-sm font-bold text-muted hover:text-violet" onClick={onBack}>&larr; Back to checks</button>
        <span className="result-meta">Report {inv.id.slice(0, 8)} · SHA-256 {inv.file.sha256.slice(0, 12)}…</span>
        <div className="flex gap-2"><Btn kind="ghost" onClick={() => void downloadReport(inv.id, "pdf")}>PDF report</Btn>
          <Btn kind="ghost" onClick={() => void downloadReport(inv.id, "json")}>JSON</Btn>
          <Btn kind="ghost" onClick={async () => { if (confirm("Delete this investigation?")) { await deleteInvestigation(inv.id); onDeleted(); } }}>Delete</Btn></div>
      </div>
      <div className="result-overview">
        <Card className="media-card">
          {mediaUrl ? (inv.kind === "image" ? <img src={mediaUrl} alt="Analysed media" className="w-full rounded-2xl" />
            : inv.kind === "audio" ? <audio src={mediaUrl} controls className="w-full" />
            : <video ref={vid} src={mediaUrl} controls className="w-full rounded-2xl" />)
            : <div className="media-placeholder" role="img" aria-label="Original media is not stored"><div className="placeholder-shape"><span /></div><p>The original isn't stored</p></div>}
          <p className="media-caption">{inv.kind === "video" ? "Sampled frames only, not a full-video analysis." : inv.kind === "audio" ? "Audio is analyzed only by the configured audio model." : "Original media preview."}</p>
          {inv.media_details && <dl className="media-details">{Object.entries(inv.media_details).map(([key, value]) => (
            <div key={key}><dt>{key.replace(/_/g, " ")}</dt><dd>{String(value)}</dd></div>
          ))}</dl>}
          {inv.kind === "video" && <div className="mt-4 px-2">
            <h3 className="mb-2 text-sm font-bold">Sampled frames ({inv.frames.length}). This is not a full-video analysis.</h3>
            {evaluatedFrames.length > 0 && <p className="mb-2 text-xs text-muted">{flaggedFrames} of {evaluatedFrames.length} analyzed sampled frames were flagged. This is not the probability that the video is manipulated.</p>}
            <div className="flex flex-wrap gap-2">{inv.frames.map((fr) => (
              <button key={fr.index} aria-label={`Frame at ${fr.time_s} seconds`} onClick={() => { setSel(fr.index); if (vid.current) vid.current.currentTime = fr.time_s; }}
                className={`rounded-xl px-3 py-2 text-xs font-bold ${sel === fr.index ? "outline outline-2 outline-ink" : ""} ${fr.stance === "supports_manipulation" ? "bg-[#FFE0A3]" : fr.stance === "supports_authenticity" ? "bg-[#BDEBDD]" : "bg-[#E3E0F5]"}`}>{fr.time_s}s</button>))}</div>
            {sel !== null && inv.frames[sel] && <p className="mt-3 text-sm text-muted">Frame {inv.frames[sel].time_s}s: {inv.frames[sel].observation}. Brightness {inv.frames[sel].brightness}, sharpness {inv.frames[sel].sharpness}.</p>}
          </div>}
          {inv.kind === "audio" && <div className="audio-timeline">
            <h3>Audio segments ({inv.audio_segments?.length ?? 0})</h3>
            {!inv.audio_segments?.length ? <p>No segment scores are available. Check the model status in the evidence below.</p> :
              <ol>{inv.audio_segments.map((segment) => <li key={segment.index}>
                <span>{segment.start_s.toFixed(1)}–{segment.end_s.toFixed(1)}s</span>
                <b>{segment.prediction}</b>
                <small>{Object.entries(segment.scores).map(([label, score]) => `${label}: ${score.toFixed(3)}`).join(" · ")}</small>
              </li>)}</ol>}
          </div>}
        </Card>
        <div className="result-summary">
          <p className="text-xs font-bold uppercase tracking-wider text-violet">The short version</p>
          <h1 className="mt-2 font-display text-4xl font-extrabold leading-tight">{HEAD[f.assessment]}</h1>
          <p className="mt-3 text-muted">{f.explanation}</p>
          <Card className="risk-card">
            <div className="flex justify-between text-xs font-bold text-muted"><span>Little evidence of edits</span><span>Strong signs of edits</span></div>
            <div className="relative mt-2 flex h-4 overflow-hidden rounded-full"><div className="flex-1 bg-[#BDEBDD]" /><div className="flex-1 bg-[#FFE0A3]" /><div className="flex-1 bg-[#FFC2B8]" />
              {pos === null && <div className="absolute inset-0 bg-white/70" />}</div>
            {pos !== null && <div className="relative h-4"><div className="absolute -top-6 h-8 w-1 rounded bg-ink" style={{ left: `${pos}%` }} /></div>}
            <p className="mt-3 text-sm">{f.calibration_note} Raw model score: {model?.status === "completed" && model.score ? JSON.stringify(model.score) : "not available"}.</p>
            <dl className="mt-3 space-y-1 text-sm">
              <div className="flex justify-between"><dt>Risk indicator</dt><dd className="font-bold">{f.risk_indicator === "UNDETERMINED" ? "Not enough information" : f.risk_indicator}</dd></div>
              <div className="flex justify-between"><dt>Calibrated probability</dt><dd className="font-bold text-muted">{f.calibrated_probability ?? "Not shown"}</dd></div></dl>
            <p className="mt-2 text-xs text-muted">{model?.score_semantics ?? f.calibration_note}</p>
          </Card>
        </div>
        {model && <ScoreChart module={model} />}
        {inv.processing_duration_s !== undefined && <p className="text-right text-xs text-muted">Processing time: {inv.processing_duration_s.toFixed(2)} seconds</p>}
      </div>
      {f.conflicts.map((c, i) => <p key={i} className="rounded-2xl bg-[#FFE0A3] p-4 text-sm font-bold text-[#6B3A00]">Conflicting findings: {c.note}</p>)}
      {inv.processing_errors.map((e, i) => <p key={i} className="rounded-2xl bg-[#FFE4DF] p-4 text-sm font-bold text-[#7A1B0C]">{e}</p>)}
      <section className="result-findings"><h2 className="mb-4 font-display text-2xl font-extrabold">What we found</h2>
        <div className="findings-grid">{inv.modules.map((m) => (
          <Card key={m.id} className="finding-card"><Chip stance={m.stance} /><h3 className="mt-3 text-lg font-bold">{m.name}</h3>
            <p className="mt-2 text-sm text-muted">{m.summary}</p>
            {m.observation && <p className="mt-2 text-xs font-bold">{m.observation}</p>}
            <p className="mt-3 text-xs text-muted">Reliability: {m.reliability}. Method: {m.method} v{m.version}.</p>
            <details className="mt-2 text-xs text-muted"><summary className="cursor-pointer font-bold">Limitations</summary><ul className="mt-1 list-disc pl-4">{m.limitations.map((l) => <li key={l}>{l}</li>)}</ul></details></Card>))}
          <Card className="finding-card"><Chip stance="could_not_check" /><h3 className="mt-3 text-lg font-bold">Audio-visual consistency</h3><p className="mt-2 text-sm text-muted">No suitable model is loaded here, so we skipped it.</p></Card>
        </div></section>
      <Card className="before-share">
        <div><h2 className="font-display text-2xl font-extrabold">Before you share it</h2>
          <p className="mt-2 text-sm">Forensics can't tell you where this came from. Source checks can.</p></div>
        <div className="source-checks">{checks.map((q) => <label key={q}><input type="checkbox" />{q}</label>)}</div>
        <details className="claim-check">
          <summary>Build a checklist from a claim</summary>
          <p className="claim-intro">No web search is connected, so nothing is looked up for you.</p>
          <textarea value={claim} onChange={(e) => { setClaim(e.target.value); setAsked(false); }} rows={2} aria-label="Claim or context" placeholder='e.g. "This video supposedly shows an event that happened today."' />
          <div className="mt-3"><Btn onClick={() => setAsked(true)} disabled={!claim.trim()}>Build checklist</Btn></div>
          {asked && <div className="claim-results">
            <div><h3 className="font-bold">Claim: "{claim.trim()}"</h3><p className="mt-2"><b>This analysis can say:</b> {f.explanation}</p>
              <p className="mt-2"><b>It cannot say:</b> when or where this was recorded, who made it, or whether the claim is true.</p></div>
            <ul>{["Who first published it? Find the earliest upload.", "What is the publication date, and does it match the claim?", "Run a reverse-image search (use a key frame for video).", "Do credible outlets report the same event with the same footage?", "Does the location, weather, clothing and language fit the claim?", "Can you contact the uploader or the people shown?"].map((q) => (
              <li key={q}><label><input type="checkbox" />{q}</label></li>))}</ul></div>}
        </details>
      </Card>
      <p className="text-center text-xs text-muted">AI detection is probabilistic and cannot guarantee authenticity. Avoid sharing potentially harmful media until you've verified its source. {inv.retention}</p>
    </div>
  );
}
