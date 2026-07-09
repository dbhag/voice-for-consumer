"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getJob } from "@/lib/api";
import type { CallResult, JobDetail } from "@/lib/types";

const POLL_INTERVAL_MS = 2000;

const TERMINAL_LABEL: Record<CallResult["terminal_state"], string> = {
  got_info: "Got info",
  refused: "Refused",
  couldnt_reach: "Couldn't reach",
};

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
        <td>{result.from_cache ? "cache" : `${result.call_minutes.toFixed(2)} min`}</td>
      </tr>
      <tr>
        <td colSpan={4}>
          {Object.keys(result.fields).length > 0 && (
            <ul className="fields">
              {Object.entries(result.fields).map(([name, field]) => (
                <li key={name}>
                  <strong>{name}:</strong>{" "}
                  {field.value === null ? (
                    <em>unknown{field.reason ? ` (${field.reason})` : ""}</em>
                  ) : (
                    String(field.value)
                  )}
                </li>
              ))}
            </ul>
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
        if (detail.status === "done" && timerRef.current) {
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
      <p>
        <Link href="/">&larr; All jobs</Link>
      </p>
      <h1>Job {jobId}</h1>

      {error && <p className="error">{error}</p>}
      {!job && !error && <p>Loading…</p>}

      {job && (
        <>
          <p>
            Status: <span className={`badge badge-${job.status}`}>{job.status}</span>
            {job.status !== "done" && " — polling every 2s…"}
          </p>

          {job.request && (
            <section className="card">
              <h2>Ask</h2>
              <p>{job.request.ask}</p>
            </section>
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
