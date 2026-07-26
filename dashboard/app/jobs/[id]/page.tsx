"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getJob } from "@/lib/api";
import type { CallResult, FieldResult, JobDetail } from "@/lib/types";

const POLL_INTERVAL_MS = 2000;

const TERMINAL_LABEL: Record<CallResult["terminal_state"], string> = {
  got_info: "Got info",
  refused: "Refused",
  couldnt_reach: "Couldn't reach",
};

function humanizeFieldName(name: string): string {
  const spaced = name.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function costLabel(result: CallResult): string {
  if (result.from_cache) return "cache";
  const parts = [`${result.call_minutes.toFixed(2)} min`];
  if (result.cost_usd !== null) parts.push(`$${result.cost_usd.toFixed(2)}`);
  return parts.join(" · ");
}

// The proof layer: source_span already exists on every grounded field
// (engine/extraction.py's hard-rule guard guarantees it), it just wasn't
// surfaced. <details>/<summary> keeps expand-to-verify native — no new
// state, no new library.
function FieldRow({ name, field }: { name: string; field: FieldResult }) {
  return (
    <div className="field-row">
      <span className="field-name">{humanizeFieldName(name)}</span>
      {field.value === null ? (
        <span className="field-value">
          <em>unknown{field.reason ? ` (${field.reason})` : ""}</em>
        </span>
      ) : (
        <details className="field-value">
          <summary>{String(field.value)}</summary>
          <blockquote className="source-span">
            {field.source_span ?? "no source span recorded"}
          </blockquote>
        </details>
      )}
    </div>
  );
}

function TranscriptCard({ result }: { result: CallResult }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="transcript-card">
      <button type="button" className="secondary" onClick={() => setOpen((o) => !o)}>
        {open ? "Hide transcript" : "Show transcript"} ({result.transcript.length} turns)
      </button>
      {open && (
        <ol className="transcript">
          {result.transcript.map((turn) => (
            <li key={turn.turn_id} className={`turn turn-${turn.speaker}`}>
              <span className="speaker">{turn.speaker}</span>
              <span className="text">{turn.text}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ResultRow({ result }: { result: CallResult }) {
  return (
    <>
      <tr>
        <td>{result.target}</td>
        <td>
          <span className={`badge badge-terminal-${result.terminal_state}`}>
            {TERMINAL_LABEL[result.terminal_state]}
          </span>
          {result.reach_failure && <span className="detail"> ({result.reach_failure})</span>}
          {result.refusal_reason && <span className="detail"> ({result.refusal_reason})</span>}
        </td>
        <td>{result.completion_level ?? "—"}</td>
        <td>{costLabel(result)}</td>
      </tr>
      <tr>
        <td colSpan={4}>
          {Object.keys(result.fields).length > 0 && (
            <div className="fields">
              {Object.entries(result.fields).map(([name, field]) => (
                <FieldRow key={name} name={name} field={field} />
              ))}
            </div>
          )}
          <TranscriptCard result={result} />
        </td>
      </tr>
    </>
  );
}

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const detail = await getJob(jobId);
        if (cancelled) return;
        setJob(detail);
        // "failed" is terminal too — polling forever on a dead job is
        // exactly the bug this status exists to prevent.
        if ((detail.status === "done" || detail.status === "failed") && timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    }

    poll();
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [jobId]);

  return (
    <main className="page">
      <Link href="/" className="back-link">
        &larr; All jobs
      </Link>
      <h1>{job?.request?.ask ?? "Job"}</h1>
      <p className="job-id">{jobId}</p>

      {error && <p className="error">{error}</p>}
      {!job && !error && <p>Loading…</p>}

      {job && (
        <>
          <p>
            Status: <span className={`badge badge-${job.status}`}>{job.status}</span>
            {(job.status === "queued" || job.status === "running") && " — polling every 2s…"}
          </p>

          {job.status === "failed" && (
            <div className="banner banner-error">
              <strong>This job failed before finishing.</strong>
              {job.error && <p>{job.error}</p>}
            </div>
          )}

          {job.results && (
            <section className="card">
              <h2>Ranked results</h2>
              <table>
                <thead>
                  <tr>
                    <th>Target</th>
                    <th>Outcome</th>
                    <th>Completion</th>
                    <th>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {job.results.map((result) => (
                    <ResultRow key={result.target} result={result} />
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}
    </main>
  );
}
