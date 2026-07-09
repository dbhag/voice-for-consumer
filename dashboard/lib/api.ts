import type { JobDetail, JobSummary, RequestPayload, SubmitJobResponse } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function listJobs(): Promise<JobSummary[]> {
  const res = await fetch(`${API_BASE_URL}/jobs`, { cache: "no-store" });
  if (!res.ok) throw new Error(`failed to list jobs: ${res.status}`);
  return res.json();
}

export async function getJob(jobId: string): Promise<JobDetail> {
  const res = await fetch(`${API_BASE_URL}/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`failed to fetch job ${jobId}: ${res.status}`);
  return res.json();
}

export async function submitJob(body: {
  request: RequestPayload;
  hint_pack?: string | null;
  notify_email?: string | null;
  acknowledge_missing_context?: boolean;
}): Promise<SubmitJobResponse> {
  const res = await fetch(`${API_BASE_URL}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`failed to submit job: ${res.status}`);
  return res.json();
}
