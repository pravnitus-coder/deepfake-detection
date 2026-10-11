import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, cancelUpload, completeUpload, initiateUpload, sha256, uploadChunk, uploadStatus } from "../api";
import type { Health, Investigation } from "../types";
import { listRecovery, removeRecovery, saveRecovery, type SavedUpload } from "../uploadRecovery";
import { Btn, mb } from "./ui";

const LIMITS = { image: 10, video: 50, audio: 30 };
const EXT: Record<string, "image" | "video" | "audio"> = {
  jpg: "image", jpeg: "image", png: "image", webp: "image",
  mp4: "video", mov: "video", avi: "video", webm: "video",
  wav: "audio", mp3: "audio", m4a: "audio", aac: "audio", flac: "audio", ogg: "audio",
};
type Phase = "idle" | "validating" | "preparing" | "uploading" | "paused" | "connection_lost" | "waiting_retry" | "resuming" | "verifying" | "analyzing" | "complete" | "failed" | "cancelled";
type MediaKind = "image" | "video" | "audio";
const MAX_RETRIES = 5;
const MAX_CONCURRENT = 2;

function transient(error: unknown) {
  return !(error instanceof ApiError) || [408, 429, 500, 502, 503, 504].includes(error.status);
}

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      reject(new DOMException("Upload paused.", "AbortError"));
    }, { once: true });
  });
}

async function fileSignatureMatches(file: File, kind: MediaKind) {
  const bytes = new Uint8Array(await file.slice(0, 16).arrayBuffer());
  const ascii = String.fromCharCode(...bytes);
  if (kind === "image") {
    return (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) ||
      ascii.startsWith("\x89PNG\r\n\x1a\n") ||
      (ascii.startsWith("RIFF") && ascii.slice(8, 12) === "WEBP");
  }
  if (kind === "video") {
    return (ascii.slice(4, 8) === "ftyp" && ascii.slice(8, 12) !== "M4A ") ||
      (bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3) ||
      (ascii.startsWith("RIFF") && ascii.slice(8, 12) === "AVI ");
  }
  return (ascii.startsWith("RIFF") && ascii.slice(8, 12) === "WAVE") ||
    ascii.startsWith("fLaC") || ascii.startsWith("OggS") || ascii.startsWith("ID3") ||
    (bytes[0] === 0xff && (bytes[1] & 0xf6) === 0xf0) ||
    (ascii.slice(4, 8) === "ftyp" && ["M4A ", "M4B ", "M4P "].includes(ascii.slice(8, 12))) ||
    (bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0);
}

export default function Upload({ onDone, userId, health }: {
  onDone: (inv: Investigation, file: File, url: string) => void;
  userId: string;
  health: Health | null;
}) {
  const [selectedKind, setSelectedKind] = useState<MediaKind>("image");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState<string>("");
  const [dur, setDur] = useState<number | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState<Awaited<ReturnType<typeof uploadStatus>> | null>(null);
  const [confirmed, setConfirmed] = useState<Set<number>>(new Set());
  const [retryCount, setRetryCount] = useState(0);
  const [speed, setSpeed] = useState(0);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const [recoveries, setRecoveries] = useState<SavedUpload[]>([]);
  const [recoveryTarget, setRecoveryTarget] = useState<SavedUpload | null>(null);
  const [simulation, setSimulation] = useState<"none" | "disconnect" | "timeout" | "http_503" | "retry_exhaust">("none");
  const [threshold, setThreshold] = useState<25 | 50 | 75>(50);
  const [recoverySeconds, setRecoverySeconds] = useState(8);
  const controller = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const fileRef = useRef<File | null>(null);
  const statusRef = useRef(status);
  const running = useRef(false);
  const urlRef = useRef(url);
  const autoResume = useRef(false);
  const kind = file ? EXT[file.name.split(".").pop()?.toLowerCase() ?? ""] : undefined;

  useEffect(() => { statusRef.current = status; }, [status]);
  useEffect(() => { fileRef.current = file; }, [file]);
  useEffect(() => { urlRef.current = url; }, [url]);
  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current); controller.current?.abort(); }, []);
  useEffect(() => {
    let mounted = true;
    listRecovery(userId).then((items) => { if (mounted) setRecoveries(items); })
      .catch((reason: unknown) => { if (mounted) setError(`Could not load saved upload sessions: ${(reason as Error).message}`); });
    return () => { mounted = false; };
  }, [userId]);
  useEffect(() => {
    const onOffline = () => {
      setOnline(false);
      if (running.current) {
        autoResume.current = true;
        setPhase("connection_lost");
        controller.current?.abort();
      }
    };
    const onOnline = () => {
      setOnline(true);
      if (autoResume.current) {
        autoResume.current = false;
        void runTransfer(true);
      }
    };
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    return () => { window.removeEventListener("offline", onOffline); window.removeEventListener("online", onOnline); };
  });

  async function remember(upload: Awaited<ReturnType<typeof uploadStatus>>, checksum: string, selected: File) {
    const entry: SavedUpload = {
      uploadId: upload.upload_id, userId, fileName: selected.name, fileSize: selected.size,
      fileType: kind ?? selectedKind, sha256: checksum,
      confirmedChunks: upload.received_chunks, updatedAt: Date.now(),
    };
    await saveRecovery(entry);
    setRecoveries(await listRecovery(userId));
  }

  async function pick(selected: File | undefined) {
    if (!selected) return;
    setError(""); setDur(null); setRecoveryTarget(null); setPhase("validating");
    const selectedFileKind = EXT[selected.name.split(".").pop()?.toLowerCase() ?? ""];
    if (!selectedFileKind) {
      setFile(null); setPhase("failed");
      return setError("Unsupported file type. Use JPG, PNG, WebP, MP4, MOV, AVI, WebM, WAV, MP3, M4A, AAC, FLAC or OGG.");
    }
    if (selectedFileKind !== selectedKind) {
      setFile(null); setPhase("failed");
      return setError(`Choose the ${selectedKind} option before selecting this file.`);
    }
    if (selected.size <= 0 || selected.size > LIMITS[selectedFileKind] * 1048576) {
      setFile(null); setPhase("failed");
      return setError(`That ${selectedFileKind} is ${mb(selected.size)}. The limit is ${LIMITS[selectedFileKind]} MB.`);
    }
    try {
      if (!await fileSignatureMatches(selected, selectedFileKind)) {
        throw new Error("The file contents do not match a supported media format.");
      }
      setFile(selected);
      const nextUrl = URL.createObjectURL(selected);
      setUrl(nextUrl);
      setPhase("idle");
      if (recoveryTarget) {
        const checksum = await sha256(selected);
        if (recoveryTarget.fileSize !== selected.size || recoveryTarget.sha256 !== checksum ||
            recoveryTarget.fileType !== selectedFileKind) {
          throw new Error("This file does not match the saved upload. Select the original file to resume it.");
        }
        setStatus(await uploadStatus(recoveryTarget.uploadId, true));
      }
    } catch (reason) {
      setPhase("failed");
      setError((reason as Error).message);
    }
  }

  async function runTransfer(resume = false) {
    if (running.current) return;
    const selected = fileRef.current;
    if (!selected) return;
    running.current = true;
    setError("");
    setPhase(resume ? "resuming" : "preparing");
    let active = statusRef.current;
    let checksum = "";
    try {
      checksum = await sha256(selected);
      if (!active) {
        const mode = simulation === "none" ? undefined : {
          fault: simulation, threshold_percent: threshold, recovery_seconds: recoverySeconds,
        } as const;
        active = await initiateUpload(selected, kind ?? selectedKind, checksum, mode);
        setStatus(active); statusRef.current = active;
      }
      if (active.expected_size !== selected.size || active.file_name !== selected.name) {
        throw new Error("The selected file does not match this upload session.");
      }
      if (active.status === "complete" && active.analysis_id) {
        throw new Error("This upload is already complete. Open its result from Past checks.");
      }
      await remember(active, checksum, selected);
      const authoritative = await uploadStatus(active.upload_id, true);
      setStatus(authoritative); statusRef.current = authoritative;
      const confirmedSet = new Set(authoritative.received_chunks);
      setConfirmed(confirmedSet);
      const queue = authoritative.missing_chunks;
      let cursor = 0;
      const controllerNow = new AbortController();
      controller.current = controllerNow;
      const initialBytes = authoritative.confirmed_bytes;
      let previousBytes = initialBytes;
      let previousAt = performance.now();
      const worker = async () => {
        while (cursor < queue.length && !controllerNow.signal.aborted && online) {
          const index = queue[cursor++];
          let retries = 0;
          while (true) {
            try {
              setPhase(resume ? "resuming" : "uploading");
              await uploadChunk(authoritative.upload_id, index, selected, authoritative.chunk_size, controllerNow.signal);
              if (controllerNow.signal.aborted) break;
              confirmedSet.add(index);
              setConfirmed(new Set(confirmedSet));
              const bytes = Math.min(selected.size, confirmedSet.size * authoritative.chunk_size -
                (confirmedSet.has(authoritative.total_chunks - 1) ? authoritative.chunk_size - (selected.size % authoritative.chunk_size || authoritative.chunk_size) : 0));
              const now = performance.now();
              setSpeed((bytes - previousBytes) * 1000 / Math.max(1, now - previousAt));
              previousBytes = bytes; previousAt = now;
              active = { ...authoritative, received_chunks: [...confirmedSet], missing_chunks: [], confirmed_bytes: bytes };
              setStatus(active); statusRef.current = active;
              await remember(active, checksum, selected);
              break;
            } catch (reason) {
              if (controllerNow.signal.aborted) break;
              if (reason instanceof ApiError && (reason.status === 401 || reason.status === 403)) throw reason;
              if (!transient(reason) || retries >= MAX_RETRIES) throw reason;
              const retryAfter = reason instanceof ApiError ? reason.retryAfterSeconds : undefined;
              const wait = retryAfter ? retryAfter * 1000 : (1000 * (2 ** retries)) * (0.8 + Math.random() * 0.4);
              retries += 1;
              setRetryCount((count) => count + 1);
              setPhase(navigator.onLine ? "waiting_retry" : "connection_lost");
              await delay(wait, controllerNow.signal);
              const fresh = await uploadStatus(authoritative.upload_id);
              for (const received of fresh.received_chunks) confirmedSet.add(received);
              if (confirmedSet.has(index)) {
                setConfirmed(new Set(confirmedSet));
                break;
              }
            }
          }
        }
      };
      const workers = Array.from({ length: Math.min(MAX_CONCURRENT, queue.length) }, () => worker());
      await Promise.all(workers);
      if (controllerNow.signal.aborted) {
        if (navigator.onLine && phase !== "connection_lost") setPhase("paused");
        const fresh = await uploadStatus(authoritative.upload_id);
        setStatus(fresh); statusRef.current = fresh; setConfirmed(new Set(fresh.received_chunks));
        await remember(fresh, checksum, selected);
        return;
      }
      const fresh = await uploadStatus(authoritative.upload_id);
      setStatus(fresh); statusRef.current = fresh; setConfirmed(new Set(fresh.received_chunks));
      await remember(fresh, checksum, selected);
      if (fresh.missing_chunks.length) {
        setPhase("paused");
        return;
      }
      setPhase("verifying");
      const result = await completeUpload(authoritative.upload_id);
      setStatus(result.upload); statusRef.current = result.upload;
      setPhase("analyzing");
      await removeRecovery(authoritative.upload_id);
      setRecoveries(await listRecovery(userId));
      setPhase("complete");
      onDone(result.investigation, selected, URL.createObjectURL(selected));
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") {
        setPhase("paused");
      } else {
        setPhase("failed");
        setError(reason instanceof Error ? reason.message : "Upload failed. Your confirmed chunks have been kept.");
      }
      const activeStatus = statusRef.current;
      if (activeStatus && checksum && !(reason instanceof ApiError && [401, 403].includes(reason.status))) {
        try {
          const authoritative = await uploadStatus(activeStatus.upload_id);
          setStatus(authoritative); statusRef.current = authoritative; setConfirmed(new Set(authoritative.received_chunks));
          await remember(authoritative, checksum, selected);
        } catch { /* Keep the original failure visible; the saved session can be reconciled when resumed. */ }
      }
    } finally {
      running.current = false;
      controller.current = null;
    }
  }

  async function cancel() {
    controller.current?.abort();
    const active = statusRef.current;
    if (active) {
      try { await cancelUpload(active.upload_id); await removeRecovery(active.upload_id); }
      catch (reason) { setError(`Could not cancel the server upload: ${(reason as Error).message}`); return; }
    }
    setStatus(null); statusRef.current = null; setConfirmed(new Set()); setPhase("cancelled");
    setRecoveries(await listRecovery(userId));
  }

  async function discardRecovery(item: SavedUpload) {
    try {
      await cancelUpload(item.uploadId);
      await removeRecovery(item.uploadId);
      setRecoveries(await listRecovery(userId));
    } catch (reason) {
      setError(`Could not remove the saved upload: ${(reason as Error).message}`);
    }
  }

  const busy = ["preparing", "uploading", "waiting_retry", "resuming", "verifying", "analyzing"].includes(phase);
  const total = status?.total_chunks ?? 0;
  const completed = confirmed.size;
  const remaining = Math.max(0, total - completed);
  const percent = file && status ? Math.min(99, status.confirmed_bytes / file.size * 100) : 0;
  const etaSeconds = speed > 0 && file && status ? Math.max(0, file.size - status.confirmed_bytes) / speed : null;

  return (
    <div className="upload-container">
      {!file && <div className="media-kind-tabs" role="tablist" aria-label="Choose media type">
        {(["image", "video", "audio"] as const).map((type) => (
          <button key={type} type="button" role="tab" aria-selected={selectedKind === type}
            className={selectedKind === type ? "active" : ""} onClick={() => { setSelectedKind(type); setError(""); }}>
            {type[0].toUpperCase() + type.slice(1)}
          </button>
        ))}
      </div>}
      <div
        onDragOver={(event) => { event.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(event) => { event.preventDefault(); setDrag(false); void pick(event.dataTransfer.files[0]); }}
        className={`upload-dropzone ${drag ? "is-dragging" : ""}`}>
        {!file && <>
          <div className="upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></svg></div>
          <h2>{phase === "validating" ? "Validating file…" : `Drop your ${selectedKind} here`}</h2>
          <p className="upload-help">{selectedKind === "image" ? "JPG, PNG or WebP" : selectedKind === "video" ? "MP4, MOV, AVI or WebM" : "WAV, MP3, M4A, AAC, FLAC or OGG"} · Max {LIMITS[selectedKind]} MB · Chunked uploads can resume after interruptions.</p>
          <div className="upload-action"><Btn disabled={phase === "validating"} onClick={() => input.current?.click()}>Choose media</Btn></div>
        </>}
        {file && <div className="space-y-4">
          {kind === "image" ? <img src={url} alt="Preview of the selected image" className="mx-auto max-h-72 rounded-2xl" />
            : kind === "audio" ? <audio src={url} controls className="mx-auto w-full max-w-md" onLoadedMetadata={(event) => setDur(event.currentTarget.duration)} />
            : <video src={url} controls className="mx-auto max-h-72 rounded-2xl" onLoadedMetadata={(event) => setDur(event.currentTarget.duration)} />}
          <p className="text-sm text-muted">{file.name} · {kind} · {mb(file.size)}{dur ? ` · ${dur.toFixed(1)} s` : ""}</p>
          <p className="text-xs text-muted">Connection: {online ? "Online (server reachability is checked per request)" : "Offline"} · {phase.replace(/_/g, " ")}</p>
          {status && <div role="status" aria-live="polite">
            <div className="h-3 overflow-hidden rounded-full bg-violet-soft"><div className="h-full bg-violet transition-all" style={{ width: `${phase === "complete" ? 100 : percent}%` }} /></div>
            <p className="mt-2 text-sm font-bold">
              {phase === "verifying" ? "Verifying assembled file and SHA-256…" :
                phase === "analyzing" ? "File verified. Running media analysis…" :
                  phase === "complete" ? "Upload and analysis complete." : `${Math.floor(percent)}% · ${completed}/${total} chunks confirmed · ${remaining} remaining`}
            </p>
            <p className="text-xs text-muted">{status.confirmed_bytes.toLocaleString()} / {file.size.toLocaleString()} bytes confirmed
              {speed > 0 ? ` · ${(speed / 1024).toFixed(0)} KB/s` : ""}
              {etaSeconds !== null && Number.isFinite(etaSeconds) ? ` · about ${Math.ceil(etaSeconds)} s remaining` : ""}
              {retryCount ? ` · ${retryCount} retries` : ""}</p>
          </div>}
          {phase === "connection_lost" && <p className="rounded-xl bg-[#FFE0A3] p-3 text-sm font-bold text-[#6B3A00]">Connection interrupted. Your confirmed upload progress is saved and will resume when connectivity returns.</p>}
          {!online && <p className="rounded-xl bg-[#FFE0A3] p-3 text-sm font-bold text-[#6B3A00]">You appear offline. Confirmed chunks are preserved; the server will be checked before resuming.</p>}
          {health?.upload_simulation_enabled && phase === "idle" && <fieldset className="grid gap-2 rounded-xl border border-[#655b91] p-3 text-left text-xs">
            <legend className="px-2 font-bold text-violet">Development-only network simulation</legend>
            <label>Failure mode <select className="ml-2 rounded bg-ground p-1" value={simulation} onChange={(event) => setSimulation(event.target.value as typeof simulation)}>
              <option value="none">Disabled</option><option value="disconnect">Connection interruption</option>
              <option value="timeout">Request timeout</option><option value="http_503">HTTP 503</option>
              <option value="retry_exhaust">Exhaust retries then recover</option>
            </select></label>
            {simulation !== "none" && <>
              <label>Interrupt after <select className="ml-2 rounded bg-ground p-1" value={threshold} onChange={(event) => setThreshold(Number(event.target.value) as 25 | 50 | 75)}>
                <option value={25}>25%</option><option value={50}>50%</option><option value={75}>75%</option>
              </select> confirmed bytes</label>
              <label>Recovery delay <input className="ml-2 w-16 rounded bg-ground p-1" type="number" min={1} max={180} value={recoverySeconds} onChange={(event) => setRecoverySeconds(Number(event.target.value))} /> seconds</label>
            </>}
          </fieldset>}
          <div className="flex flex-wrap justify-center gap-3">
            {!busy && phase !== "complete" && <Btn disabled={!online} onClick={() => void runTransfer(!!status)}>{phase === "failed" ? "Retry now" : status ? "Resume upload" : "Start secure upload"}</Btn>}
            {phase === "uploading" && <Btn kind="ghost" onClick={() => { controller.current?.abort(); setPhase("paused"); }}>Pause</Btn>}
            {phase === "paused" && <Btn onClick={() => void runTransfer(true)}>Resume</Btn>}
            {phase === "waiting_retry" && <Btn kind="ghost" onClick={() => controller.current?.abort()}>Pause retries</Btn>}
            {(busy || status) && phase !== "complete" && <Btn kind="ghost" onClick={() => void cancel()}>Cancel upload</Btn>}
            {!busy && phase !== "complete" && !status && <Btn kind="ghost" onClick={() => { setFile(null); setPhase("idle"); setError(""); }}>Choose another</Btn>}
            {phase === "complete" && <Btn kind="ghost" onClick={() => { setFile(null); setStatus(null); statusRef.current = null; setPhase("idle"); }}>Check another</Btn>}
          </div>
        </div>}
        {error && <p role="alert" className="mt-4 rounded-xl bg-[#FFE4DF] px-4 py-3 text-sm font-bold text-[#7A1B0C]">{error}</p>}
        {!file && recoveries.length > 0 && <div className="mt-4 grid gap-2 text-left">
          <h3 className="text-sm font-bold">Saved uploads — reselect the original file to resume</h3>
          {recoveries.map((item) => <div key={item.uploadId} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-ground p-3 text-xs">
            <span>{item.fileName} · {mb(item.fileSize)} · {item.confirmedChunks.length} acknowledged chunks</span>
            <span className="flex gap-2">
              <Btn kind="ghost" onClick={() => { setRecoveryTarget(item); input.current?.click(); }}>Choose file</Btn>
              <Btn kind="ghost" onClick={() => void discardRecovery(item)}>Remove</Btn>
            </span>
          </div>)}
        </div>}
        <input ref={input} type="file" className="hidden" aria-label={`Choose ${selectedKind} file`} accept={
          selectedKind === "image" ? ".jpg,.jpeg,.png,.webp" :
            selectedKind === "video" ? ".mp4,.mov,.avi,.webm" : ".wav,.mp3,.m4a,.aac,.flac,.ogg"
        } onChange={(event) => { void pick(event.target.files?.[0]); event.currentTarget.value = ""; }} />
      </div>
    </div>
  );
}
