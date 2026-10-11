import { useRef, useState } from "react";
import { deleteInvestigation, downloadReport } from "../api";
import type { Investigation } from "../types";
import { Btn, Card, Chip, ConfirmModal, mb } from "./ui";
import ScoreChart from "./ScoreChart";
import AudioWaveform from "./AudioWaveform";

const HEAD = {
  likely_manipulated: "This may be AI-generated or manipulated.",
  no_strong_evidence: "No strong signs of manipulation found.",
  inconclusive: "We're not sure. Here's why.",
} as const;

const POS: Record<string, number | null> = { LOW: 12, MODERATE: 50, HIGH: 88, UNDETERMINED: null };

export default function Result({
  inv,
  mediaUrl,
  onBack,
  onDeleted,
}: {
  inv: Investigation;
  mediaUrl?: string;
  onBack: () => void;
  onDeleted: () => void;
}) {
  const vid = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [sel, setSel] = useState<number | null>(inv.frames.length > 0 ? 0 : null);
  const [claim, setClaim] = useState("");
  const [asked, setAsked] = useState(false);
  const [copiedHash, setCopiedHash] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [audioCurrentTime, setAudioCurrentTime] = useState(0);
  const [audioDuration, setAudioDuration] = useState(0);

  const f = inv.fusion;
  const pos = POS[f.risk_indicator];
  const model = inv.modules.find((m) => m.id === "ai_model" || m.id === "audio_model" || m.id === "video_frames");
  const evaluatedFrames = inv.frames.filter((frame) => frame.model_status === "completed");
  const flaggedFrames = evaluatedFrames.filter((frame) => frame.stance === "supports_manipulation").length;
  const checks = [
    "Find the original publisher or earliest post date",
    "Run a reverse-image search on key frames",
    "Cross-reference with credible news and fact-checking outlets",
    "Examine context (location, weather, metadata shadows, audio sync)",
  ];

  const selectedFrame = sel !== null ? inv.frames[sel] ?? null : null;

  async function copySha256() {
    try {
      await navigator.clipboard.writeText(inv.file.sha256);
      setCopiedHash(true);
      setTimeout(() => setCopiedHash(false), 2000);
    } catch {
      /* fallback if clipboard permissions denied */
    }
  }

  return (
    <div className="result-page">
      {/* Top Toolbar */}
      <div className="result-toolbar">
        <button
          className="inline-flex items-center gap-1.5 text-xs font-bold text-muted hover:text-white transition"
          onClick={onBack}
        >
          &larr; Back to checks
        </button>
        <span className="result-meta font-mono">
          Report <span className="text-ink font-bold">{inv.id.slice(0, 8)}</span> · SHA-256{" "}
          <span className="text-ink font-bold">{inv.file.sha256.slice(0, 10)}…</span>
        </span>
        <div className="flex gap-2">
          <Btn kind="ghost" onClick={() => void downloadReport(inv.id, "pdf")} title="Download forensic PDF report">
            PDF report
          </Btn>
          <Btn kind="ghost" onClick={() => void downloadReport(inv.id, "json")} title="Download full JSON dataset">
            JSON
          </Btn>
          <Btn kind="danger" onClick={() => setDeleteConfirmOpen(true)} title="Delete investigation record">
            Delete
          </Btn>
        </div>
      </div>

      {/* Main Overview Layout */}
      <div className="result-overview">
        {/* Left Column: Media Player & Signal Inspection */}
        <div className="space-y-4">
          <Card className="media-card">
            {mediaUrl ? (
              inv.kind === "image" ? (
                <img src={mediaUrl} alt="Analysed media preview" className="w-full rounded-2xl border border-[#2a3456]" />
              ) : inv.kind === "audio" ? (
                <div className="space-y-3">
                  <audio
                    ref={audioRef}
                    src={mediaUrl}
                    controls
                    className="w-full rounded-xl"
                    onTimeUpdate={(e) => setAudioCurrentTime(e.currentTarget.currentTime)}
                    onLoadedMetadata={(e) => setAudioDuration(e.currentTarget.duration)}
                  />
                  <AudioWaveform
                    audioUrl={mediaUrl}
                    duration={audioDuration || (Number(inv.media_details?.duration_seconds) || 0)}
                    segments={inv.audio_segments}
                    currentTime={audioCurrentTime}
                    onSeek={(time) => {
                      if (audioRef.current) {
                        audioRef.current.currentTime = time;
                        void audioRef.current.play();
                      }
                    }}
                  />
                </div>
              ) : (
                <div className="space-y-3">
                  <video
                    ref={vid}
                    src={mediaUrl}
                    controls
                    className="w-full rounded-2xl border border-[#2a3456]"
                  />
                  <p className="text-[11px] text-muted text-center">
                    Click any sampled frame below to jump the video to that timestamp.
                  </p>
                </div>
              )
            ) : (
              <div className="media-placeholder" role="img" aria-label="Original media is not stored">
                <div className="placeholder-shape">
                  <span />
                </div>
                <p>Original media was securely deleted after analysis</p>
              </div>
            )}

            {/* Media Details Summary */}
            <div className="mt-3 pt-3 border-t border-[#1e253e]">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="font-bold text-white uppercase font-mono tracking-wider text-[11px]">
                  File Fingerprint
                </span>
                <button
                  type="button"
                  onClick={() => void copySha256()}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#2a3456] bg-[#161c31] px-2 py-1 text-[10px] font-mono text-cyan-300 hover:border-violet transition"
                  title="Copy full SHA-256 hash"
                >
                  {copiedHash ? "✓ Copied SHA-256" : "Copy SHA-256"}
                </button>
              </div>
              <p className="mt-1 font-mono text-[10px] text-muted break-all">{inv.file.sha256}</p>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
                <span>Format: <b className="text-ink">{inv.file.mime}</b></span>
                <span>Size: <b className="text-ink">{mb(inv.file.size_bytes)}</b> ({inv.file.size_bytes.toLocaleString()} bytes)</span>
                {inv.processing_duration_s !== undefined && (
                  <span>Analysis: <b className="text-ink">{inv.processing_duration_s.toFixed(2)}s</b></span>
                )}
              </div>
            </div>

            {/* Additional Media Metadata */}
            {inv.media_details && Object.keys(inv.media_details).length > 0 && (
              <dl className="media-details">
                {Object.entries(inv.media_details).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key.replace(/_/g, " ")}</dt>
                    <dd>{String(value)}</dd>
                  </div>
                ))}
              </dl>
            )}

            {/* Video Sampled Frames Inspector */}
            {inv.kind === "video" && (
              <div className="mt-4 rounded-xl border border-[#232b45] bg-[#0e1222] p-3.5">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-bold text-white">
                    Sampled Video Frames ({inv.frames.length})
                  </h3>
                  <span className="text-[10px] text-muted font-mono">
                    {flaggedFrames} / {evaluatedFrames.length || inv.frames.length} flagged
                  </span>
                </div>
                <p className="text-[11px] text-muted mb-3 leading-relaxed">
                  SATYAM AI extracts keyframes at fixed intervals to analyze visual cues. This is an inspection of sampled frames, not temporal video deepfake detection.
                </p>

                {/* Frame buttons */}
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {inv.frames.map((fr) => {
                    const isSelected = sel === fr.index;
                    const isFlagged = fr.stance === "supports_manipulation";
                    const isAuthentic = fr.stance === "supports_authenticity";
                    return (
                      <button
                        key={fr.index}
                        aria-label={`Frame at ${fr.time_s} seconds`}
                        onClick={() => {
                          setSel(fr.index);
                          if (vid.current) {
                            vid.current.currentTime = fr.time_s;
                          }
                        }}
                        className={`rounded-lg px-2.5 py-1 text-[11px] font-mono transition border ${
                          isSelected
                            ? "border-violet bg-violet text-white ring-2 ring-violet/40 font-bold"
                            : isFlagged
                            ? "border-amber-700/60 bg-amber-950/40 text-amber-200 hover:border-amber-500"
                            : isAuthentic
                            ? "border-emerald-700/60 bg-emerald-950/40 text-emerald-200 hover:border-emerald-500"
                            : "border-[#2a3456] bg-[#171f38] text-muted hover:border-violet"
                        }`}
                      >
                        {fr.time_s.toFixed(1)}s
                      </button>
                    );
                  })}
                </div>

                {/* Detailed selected frame inspector */}
                {selectedFrame && (
                  <div className="rounded-xl border border-[#232b45] bg-[#14192b] p-3 text-xs space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-white font-mono">
                        Frame #{selectedFrame.index + 1} ({selectedFrame.time_s.toFixed(1)}s)
                      </span>
                      <Chip stance={selectedFrame.stance} />
                    </div>
                    {selectedFrame.observation && (
                      <p className="text-ink text-[11px] leading-relaxed">
                        <b>Observation:</b> {selectedFrame.observation}
                      </p>
                    )}
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted font-mono pt-1 border-t border-[#1f2640]">
                      {selectedFrame.brightness !== undefined && (
                        <span>Brightness: <b className="text-ink">{selectedFrame.brightness}</b></span>
                      )}
                      {selectedFrame.sharpness !== undefined && (
                        <span>Sharpness: <b className="text-ink">{selectedFrame.sharpness}</b></span>
                      )}
                      {selectedFrame.model_status && (
                        <span>Classifier: <b className="text-ink">{selectedFrame.model_status}</b></span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Audio segments inspection */}
            {inv.kind === "audio" && (
              <div className="mt-4 rounded-xl border border-[#232b45] bg-[#0e1222] p-3.5">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-bold text-white">
                    Discrete Inference Windows ({inv.audio_segments?.length ?? 0})
                  </h3>
                  <span className="text-[10px] text-muted font-mono">Segmented windows</span>
                </div>
                {!inv.audio_segments?.length ? (
                  <p className="text-xs text-muted">
                    No segment scores available. The audio classifier may not be configured on this backend.
                  </p>
                ) : (
                  <ol className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                    {inv.audio_segments.map((segment) => (
                      <li
                        key={segment.index}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-[#14192b] p-2 text-xs border border-[#20273f]"
                      >
                        <span className="font-mono text-[11px] text-cyan-300">
                          {segment.start_s.toFixed(1)}s – {segment.end_s.toFixed(1)}s
                        </span>
                        <b className="text-white text-xs">{segment.prediction}</b>
                        <small className="w-full font-mono text-[10px] text-muted">
                          {Object.entries(segment.scores)
                            .map(([label, score]) => `${label}: ${score.toFixed(3)}`)
                            .join(" · ")}
                        </small>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* Right Column: Forensic Assessment & Explainability */}
        <div className="result-summary space-y-4">
          <div>
            <span className="text-[11px] font-bold uppercase tracking-wider text-violet">
              Forensic Synthesis
            </span>
            <h1 className="mt-1 font-display text-3xl font-extrabold leading-tight text-white">
              {HEAD[f.assessment]}
            </h1>
            <p className="mt-2 text-sm text-muted leading-relaxed">{f.explanation}</p>
          </div>

          {/* Risk Indicator Card */}
          <Card className="risk-card">
            <div className="flex justify-between text-[11px] font-bold text-muted">
              <span>Little evidence of edits</span>
              <span>Strong signs of edits</span>
            </div>
            <div className="relative mt-2 flex h-3.5 overflow-hidden rounded-full">
              <div className="flex-1 bg-[#BDEBDD]" title="Low risk band" />
              <div className="flex-1 bg-[#FFE0A3]" title="Moderate risk band" />
              <div className="flex-1 bg-[#FFC2B8]" title="High risk band" />
              {pos === null && <div className="absolute inset-0 bg-white/70" />}
            </div>
            {pos !== null && (
              <div className="relative h-4">
                <div
                  className="absolute -top-5 h-7 w-1 rounded-full bg-ink shadow-md"
                  style={{ left: `${pos}%` }}
                />
              </div>
            )}
            <dl className="mt-4 space-y-1.5 text-xs">
              <div className="flex justify-between">
                <dt className="text-muted">Risk indicator</dt>
                <dd className="font-bold text-ink">
                  {f.risk_indicator === "UNDETERMINED" ? "Not enough information" : f.risk_indicator}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">Calibrated probability</dt>
                <dd className="font-bold text-muted">
                  {f.calibrated_probability !== null ? `${f.calibrated_probability}` : "Not claimed (uncalibrated)"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">Synthesis method</dt>
                <dd className="font-mono text-ink text-[11px]">{f.method}</dd>
              </div>
            </dl>
            <p className="mt-3 text-[11px] text-muted leading-relaxed border-t border-[#1f2640] pt-2.5">
              <b>Calibration note:</b> {f.calibration_note}
            </p>
            {model?.status === "completed" && Boolean(model.score) && (
              <p className="mt-1.5 text-[11px] font-mono text-muted/80">
                Raw classifier score: {JSON.stringify(model.score)}
              </p>
            )}
          </Card>

          {/* Supported Score Breakdown Chart */}
          {model && <ScoreChart module={model} />}
        </div>
      </div>

      {/* Conflicts and Processing Errors */}
      {f.conflicts.map((c, i) => (
        <div key={i} className="rounded-2xl border border-amber-600/50 bg-[#291e0a] p-4 text-xs font-semibold text-amber-200">
          <b>⚠️ Conflicting Findings:</b> {c.note}
        </div>
      ))}
      {inv.processing_errors.map((e, i) => (
        <div key={i} className="rounded-2xl border border-red-800/50 bg-[#2d1214] p-4 text-xs font-semibold text-red-200">
          <b>⚠️ Processing Notice:</b> {e}
        </div>
      ))}

      {/* Forensic Findings Grid */}
      <section className="result-findings">
        <h2 className="mb-3 font-display text-2xl font-extrabold text-white">
          Individual Module Findings
        </h2>
        <div className="findings-grid">
          {inv.modules.map((m) => (
            <Card key={m.id} className="finding-card">
              <div className="flex items-center justify-between mb-2">
                <Chip stance={m.stance} />
                <span className="text-[10px] font-mono text-muted">{m.status}</span>
              </div>
              <h3 className="font-bold text-white text-sm">{m.name}</h3>
              <p className="mt-1.5 text-xs text-muted leading-relaxed">{m.summary}</p>
              {m.observation && (
                <div className="mt-2 rounded-lg bg-[#0e1220] p-2 text-[11px] font-medium text-ink">
                  {m.observation}
                </div>
              )}
              <div className="mt-2.5 text-[10px] text-muted">
                <span>Reliability: <b>{m.reliability}</b></span> · <span>Method: {m.method} v{m.version}</span>
              </div>
              {m.limitations.length > 0 && (
                <details className="mt-2 text-[10px] text-muted">
                  <summary className="cursor-pointer font-bold hover:text-white">Known limitations</summary>
                  <ul className="mt-1 list-disc pl-4 space-y-0.5">
                    {m.limitations.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                </details>
              )}
            </Card>
          ))}
          <Card className="finding-card opacity-70">
            <div className="flex items-center justify-between mb-2">
              <Chip stance="could_not_check" />
              <span className="text-[10px] font-mono text-muted">unavailable</span>
            </div>
            <h3 className="font-bold text-white text-sm">Audio-visual lip-sync check</h3>
            <p className="mt-1.5 text-xs text-muted leading-relaxed">
              No audiovisual cross-modal synchronization model is loaded. This capability remains explicitly unavailable.
            </p>
          </Card>
        </div>
      </section>

      {/* Pre-Distribution Verification Checklist */}
      <Card className="before-share">
        <div>
          <h2 className="font-display text-2xl font-extrabold">Before You Share It</h2>
          <p className="mt-2 text-sm text-[#cfc8f5]">
            Automated media forensics can identify digital artifacts, but cannot verify the true human context, recording date, or publisher intent.
          </p>
        </div>
        <div className="source-checks">
          {checks.map((q) => (
            <label key={q} className="flex items-start gap-2.5 text-xs cursor-pointer">
              <input type="checkbox" className="mt-0.5 rounded border-[#3e3860] bg-[#120f26]" />
              <span>{q}</span>
            </label>
          ))}
        </div>
        <details className="claim-check">
          <summary className="cursor-pointer font-bold text-cyan-300 hover:underline">
            Context Checklist Generator (Claim Analysis)
          </summary>
          <p className="claim-intro text-xs text-[#cfc8f5]">
            Enter the claim or headline accompanying this media to generate contextual verification questions.
          </p>
          <textarea
            value={claim}
            onChange={(e) => { setClaim(e.target.value); setAsked(false); }}
            rows={2}
            aria-label="Claim or context"
            placeholder='e.g. "This video claims to show a protest taking place in downtown today."'
            className="w-full rounded-xl bg-[#0d1020] p-3 text-xs text-white border border-[#2a3456] focus:border-violet focus:outline-none"
          />
          <div className="mt-2">
            <Btn onClick={() => setAsked(true)} disabled={!claim.trim()}>
              Generate Context Questions
            </Btn>
          </div>
          {asked && (
            <div className="claim-results">
              <div>
                <h3 className="font-bold text-white text-xs">Evaluated Context: "{claim.trim()}"</h3>
                <p className="mt-2 text-xs">
                  <b>What forensics tells you:</b> {f.explanation}
                </p>
                <p className="mt-1.5 text-xs text-amber-200">
                  <b>What forensics cannot answer:</b> Who authored the media, when or where it was recorded, or whether the accompanying text claim is factually accurate.
                </p>
              </div>
              <ul className="text-xs space-y-1.5">
                {[
                  "Who published the media first? Locate the earliest indexed upload.",
                  "Does the publication timestamp match the purported event date?",
                  "Run a reverse-image search on sampled keyframes.",
                  "Do credible regional news outlets corroborate the incident?",
                  "Do weather, architecture, street signs, and clothing match the stated location?",
                ].map((q) => (
                  <li key={q}>
                    <label className="flex items-start gap-2 cursor-pointer">
                      <input type="checkbox" className="mt-0.5" />
                      <span>{q}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </details>
      </Card>

      <p className="text-center text-xs text-muted">
        AI authenticity detection is probabilistic and cannot guarantee authenticity. {inv.retention}
      </p>

      {/* Confirm Deletion Modal */}
      <ConfirmModal
        isOpen={deleteConfirmOpen}
        title="Delete Investigation"
        message="Are you sure you want to permanently delete this investigation from the server? All forensic reports, charts, and associated logs will be removed."
        confirmLabel="Delete"
        isDanger
        onConfirm={async () => {
          await deleteInvestigation(inv.id);
          setDeleteConfirmOpen(false);
          onDeleted();
        }}
        onCancel={() => setDeleteConfirmOpen(false)}
      />
    </div>
  );
}
