import { useEffect, useRef, useState } from "react";
import type { AudioSegment } from "../types";

interface Props {
  audioUrl?: string;
  duration?: number;
  segments?: AudioSegment[];
  currentTime?: number;
  onSeek?: (time: number) => void;
}

export default function AudioWaveform({ audioUrl, duration = 0, segments = [], currentTime = 0, onSeek }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [hoverTime, setHoverTime] = useState<number | null>(null);

  useEffect(() => {
    if (!audioUrl) return;
    let active = true;
    setLoading(true);
    setError(false);

    async function extractPeaks() {
      try {
        const response = await fetch(audioUrl!);
        const arrayBuffer = await response.arrayBuffer();
        const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const ctx = new AudioCtx();
        const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
        const channelData = audioBuffer.getChannelData(0);
        const barCount = 140;
        const step = Math.floor(channelData.length / barCount);
        const extracted: number[] = [];

        for (let i = 0; i < barCount; i++) {
          const start = i * step;
          let sum = 0;
          for (let j = 0; j < step; j++) {
            sum += Math.abs(channelData[start + j] || 0);
          }
          extracted.push(sum / step);
        }

        const max = Math.max(...extracted, 0.001);
        const normalized = extracted.map((val) => Math.min(1, Math.max(0.08, val / max)));

        if (active) {
          setPeaks(normalized);
          setLoading(false);
        }
        void ctx.close();
      } catch {
        if (active) {
          setError(true);
          setLoading(false);
          // Fallback procedural waveform peaks
          const fallback = Array.from({ length: 100 }, (_, i) => 0.2 + 0.6 * Math.abs(Math.sin((i / 100) * Math.PI * 4)));
          setPeaks(fallback);
        }
      }
    }

    void extractPeaks();
    return () => { active = false; };
  }, [audioUrl]);

  // Render canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !peaks.length) return;
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const totalBars = peaks.length;
    const barSpacing = 2;
    const barWidth = Math.max(2, (width - (totalBars - 1) * barSpacing) / totalBars);
    const playbackRatio = duration > 0 ? Math.min(1, currentTime / duration) : 0;
    const activeBarIndex = Math.floor(playbackRatio * totalBars);

    // Draw baseline center
    ctx.strokeStyle = "rgba(42, 51, 82, 0.6)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, height / 2);
    ctx.lineTo(width, height / 2);
    ctx.stroke();

    // Draw amplitude bars
    peaks.forEach((peak, i) => {
      const x = i * (barWidth + barSpacing);
      const barHeight = Math.max(4, peak * (height * 0.78));
      const y = (height - barHeight) / 2;
      const isPast = i <= activeBarIndex;

      // Color scheme
      if (isPast) {
        ctx.fillStyle = "#795BFF";
      } else {
        ctx.fillStyle = "#2D3758";
      }

      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(x, y, barWidth, barHeight, 2) : ctx.rect(x, y, barWidth, barHeight);
      ctx.fill();
    });

    // Draw playhead cursor
    if (duration > 0 && playbackRatio > 0 && playbackRatio <= 1) {
      const playheadX = playbackRatio * width;
      ctx.strokeStyle = "#38BDF8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(playheadX, 0);
      ctx.lineTo(playheadX, height);
      ctx.stroke();

      ctx.fillStyle = "#38BDF8";
      ctx.beginPath();
      ctx.arc(playheadX, 4, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }, [peaks, currentTime, duration]);

  function handleCanvasClick(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!canvasRef.current || duration <= 0 || !onSeek) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, clickX / rect.width));
    onSeek(ratio * duration);
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!canvasRef.current || duration <= 0) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setHoverTime(ratio * duration);
  }

  return (
    <div className="rounded-2xl border border-[#232b45] bg-[#101424] p-4 text-ink">
      <div className="flex items-center justify-between text-xs mb-2">
        <span className="font-bold flex items-center gap-1.5 text-white">
          <svg className="w-3.5 h-3.5 text-violet" fill="currentColor" viewBox="0 0 20 20">
            <path d="M18 3a1 1 0 00-1.196-.98l-10 2A1 1 0 006 5v9.114A4.369 4.369 0 005 14c-1.657 0-3 .895-3 2s1.343 2 3 2 3-.895 3-2V7.82l8-1.6v5.894A4.37 4.37 0 0015 12c-1.657 0-3 .895-3 2s1.343 2 3 2 3-.895 3-2V3z" />
          </svg>
          Audio Amplitude & Segment Timeline
        </span>
        <span className="text-[11px] font-mono text-muted">
          {currentTime.toFixed(1)}s / {duration.toFixed(1)}s
          {hoverTime !== null && ` (Seek: ${hoverTime.toFixed(1)}s)`}
        </span>
      </div>

      {loading ? (
        <div className="h-24 flex items-center justify-center text-xs text-muted">
          <span className="animate-pulse">Decoding audio waveform…</span>
        </div>
      ) : (
        <div className="relative">
          <canvas
            ref={canvasRef}
            onClick={handleCanvasClick}
            onMouseMove={handleMouseMove}
            onMouseLeave={() => setHoverTime(null)}
            className="h-24 w-full cursor-pointer rounded-xl bg-[#090d1a]"
            title="Click anywhere to seek"
          />
        </div>
      )}

      {/* Segment bounds marker overview */}
      {segments.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] font-bold text-muted mb-1.5 flex justify-between">
            <span>Inference Segments ({segments.length})</span>
            <span className="text-[10px] text-muted">Click segment to play</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {segments.map((seg) => {
              const isActive = currentTime >= seg.start_s && currentTime <= seg.end_s;
              const isFlagged = seg.prediction.toLowerCase().includes("fake") || seg.prediction.toLowerCase().includes("manipulated");
              return (
                <button
                  key={seg.index}
                  type="button"
                  onClick={() => onSeek && onSeek(seg.start_s)}
                  className={`rounded-lg px-2 py-1 text-[10px] font-mono transition border ${
                    isActive
                      ? "border-cyan-400 bg-cyan-950/60 text-cyan-200"
                      : isFlagged
                      ? "border-amber-700/60 bg-amber-950/30 text-amber-300 hover:border-amber-500"
                      : "border-[#2a3352] bg-[#161c31] text-muted hover:border-violet"
                  }`}
                >
                  {seg.start_s.toFixed(1)}–{seg.end_s.toFixed(1)}s: <b>{seg.prediction}</b>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <p className="mt-2.5 text-[10px] text-muted leading-relaxed">
        <b>Explainability Note:</b> The waveform illustrates relative sample energy over time. Raw audio classifier scores are descriptive model inferences from discrete segment windows, not conclusive forensic proof of synthetic speech or voice cloning.
      </p>
    </div>
  );
}
