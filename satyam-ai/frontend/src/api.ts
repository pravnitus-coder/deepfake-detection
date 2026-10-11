import type { Health, Investigation } from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ??
  (window.location.protocol === "file:" ? "http://localhost:8000" : "");
const AUTH_KEY = "satyam.access-token";
let accessToken = sessionStorage.getItem(AUTH_KEY) ?? "";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly retryAfterSeconds?: number) {
    super(message);
  }
}

export function setAccessToken(token: string) {
  accessToken = token;
  if (token) sessionStorage.setItem(AUTH_KEY, token);
  else sessionStorage.removeItem(AUTH_KEY);
}

async function err(r: Response): Promise<never> {
  let message = `Request failed (${r.status}).`;
  try {
    const body = await r.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (body.detail?.message) message = body.detail.message;
  } catch { /* preserve the HTTP status message */ }
  const retryAfter = Number(r.headers.get("retry-after"));
  throw new ApiError(message, r.status, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined);
}

export async function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  return fetch(`${BASE}${path}`, { ...init, headers });
}

export interface AuthReply { user_id: string; username: string; access_token: string; token_type: "bearer"; expires_in: number }
export async function authenticate(mode: "login" | "register", username: string, password: string): Promise<AuthReply> {
  const response = await fetch(`${BASE}/api/auth/${mode}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) return err(response);
  return response.json();
}

export async function logout() {
  const response = await apiFetch("/api/auth/logout", { method: "POST" });
  if (!response.ok) return err(response);
}

export async function currentUser() {
  const response = await apiFetch("/api/auth/me");
  if (!response.ok) return err(response);
  return response.json() as Promise<{ user_id: string }>;
}

export const health = async (): Promise<Health> => {
  const response = await fetch(`${BASE}/api/health`);
  if (!response.ok) return err(response);
  return response.json();
};
export const getInvestigation = async (id: string): Promise<Investigation> => {
  const response = await apiFetch(`/api/analysis/${encodeURIComponent(id)}`);
  if (!response.ok) return err(response);
  return response.json();
};
export const getHistory = async (): Promise<Investigation[]> => {
  const response = await apiFetch("/api/analysis/history");
  if (!response.ok) return err(response);
  return response.json();
};
export const deleteInvestigation = async (id: string) => {
  const response = await apiFetch(`/api/analysis/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!response.ok && response.status !== 404) return err(response);
};

export async function downloadReport(id: string, format: "pdf" | "json") {
  const response = await apiFetch(`/api/analysis/${encodeURIComponent(id)}/report${format === "pdf" ? ".pdf" : ""}`);
  if (!response.ok) return err(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `satyam-report-${id}.${format}`;
  link.click();
  URL.revokeObjectURL(url);
}

export interface UploadStatus {
  upload_id: string;
  file_name: string;
  media_type: "image" | "video" | "audio";
  expected_size: number;
  chunk_size: number;
  total_chunks: number;
  received_chunks: number[];
  missing_chunks: number[];
  confirmed_bytes: number;
  status: "uploading" | "verifying" | "complete" | "failed";
  expires_at: string;
  analysis_id: string | null;
}
export interface UploadSimulation {
  fault: "disconnect" | "timeout" | "http_503" | "retry_exhaust";
  threshold_percent: 25 | 50 | 75;
  recovery_seconds: number;
}

export async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function initiateUpload(file: File, kind: "image" | "video" | "audio",
                                     checksum: string, simulation?: UploadSimulation): Promise<UploadStatus> {
  const response = await apiFetch("/api/uploads/initiate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      media_type: kind, file_name: file.name, file_size: file.size,
      file_sha256: checksum, mime_type: file.type || "application/octet-stream", simulation,
    }),
  });
  if (!response.ok) return err(response);
  return response.json();
}

export async function uploadStatus(uploadId: string, resume = false): Promise<UploadStatus> {
  const response = await apiFetch(`/api/uploads/${encodeURIComponent(uploadId)}/${resume ? "resume" : "status"}`,
    resume ? { method: "POST" } : {});
  if (!response.ok) return err(response);
  return response.json();
}

export async function uploadChunk(uploadId: string, index: number, file: File, chunkSize: number,
                                  signal: AbortSignal): Promise<void> {
  const start = index * chunkSize;
  const end = Math.min(file.size, start + chunkSize);
  const blob = file.slice(start, end);
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  const checksum = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  const response = await apiFetch(`/api/uploads/${encodeURIComponent(uploadId)}/chunks/${index}`, {
    method: "PUT",
    headers: {
      "Content-Range": `bytes ${start}-${end - 1}/${file.size}`,
      "X-Chunk-SHA256": checksum,
      "Content-Type": "application/octet-stream",
    },
    body: blob,
    signal,
  });
  if (!response.ok) return err(response);
}

export async function completeUpload(uploadId: string): Promise<{ upload: UploadStatus; investigation: Investigation }> {
  const response = await apiFetch(`/api/uploads/${encodeURIComponent(uploadId)}/complete`, { method: "POST" });
  if (!response.ok) return err(response);
  return response.json();
}

export async function cancelUpload(uploadId: string) {
  const response = await apiFetch(`/api/uploads/${encodeURIComponent(uploadId)}`, { method: "DELETE" });
  if (!response.ok) return err(response);
}

export interface FeedbackSubmission {
  name?: string;
  role?: "Student" | "Developer" | "Researcher" | "Journalist" | "Other";
  rating: number;
  worked_as_expected?: "yes" | "partially" | "no";
  liked?: string;
  confusing?: string;
  feature_to_improve?: string;
  bugs?: string;
  suggestions?: string;
  consent_to_publish?: boolean;
}

export interface FeedbackResponse {
  id: string;
  message: string;
  created_at: string;
}

export async function submitFeedback(data: FeedbackSubmission): Promise<FeedbackResponse> {
  const response = await apiFetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) return err(response);
  return response.json();
}

