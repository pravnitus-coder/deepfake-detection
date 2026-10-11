export type Stance = "supports_manipulation" | "supports_authenticity" | "inconclusive" | "could_not_check";
export interface Module { id: string; name: string; status: "completed" | "unavailable" | "failed"; stance: Stance; method: string; version: string;
  observation: string | null; score: unknown; score_semantics: string | null; summary: string; limitations: string[]; reliability: string; details?: Record<string, unknown>; }
export interface Frame { index: number; time_s: number; status: string; stance: Stance; observation?: string; brightness?: number; sharpness?: number; model_scores?: Record<string, number> | null; model_status?: string; }
export interface Fusion { assessment: "likely_manipulated" | "no_strong_evidence" | "inconclusive"; risk_indicator: string; calibrated_probability: number | null;
  calibration_note: string; explanation: string; rules: string; method: string; conflicts: { note: string }[]; unavailable: { id: string; reason: string }[]; }
export interface AudioSegment { index: number; start_s: number; end_s: number; prediction: string; scores: Record<string, number>; }
export interface Investigation { id: string; created_at: string; kind: "image" | "video" | "audio"; file: { sha256: string; size_bytes: number; mime: string };
  modules: Module[]; fusion: Fusion; frames: Frame[]; audio_segments?: AudioSegment[]; media_details?: Record<string, string | number>;
  processing_duration_s?: number; processing_errors: string[]; retention: string; }
export interface Health {
  status: string;
  model: { ready: boolean; name: string; reason: string | null };
  audio_model?: { ready: boolean; name: string; reason: string | null };
  upload_simulation_enabled?: boolean;
  upload_chunk_size_bytes?: number;
  upload_max_concurrent_chunks?: number;
  upload_max_retries?: number;
  upload_retry_delays_seconds?: number[];
  upload_request_timeout_seconds?: number;
  modules: Record<string, string>;
}
