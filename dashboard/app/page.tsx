"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { listJobs, submitJob } from "@/lib/api";
import type { JobSummary, MissingContext } from "@/lib/types";

type ContextRow = { key: string; value: string };

const STATE_LABEL: Record<JobSummary["status"], string> = {
  queued: "Queued",
  running: "Running",
  done: "Done",
  failed: "Failed",
};

export default function HomePage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);

  const [ask, setAsk] = useState("");
  const [returnFields, setReturnFields] = useState("");
  const [contextRows, setContextRows] = useState<ContextRow[]>([]);
  const [targets, setTargets] = useState("");
  const [notifyEmail, setNotifyEmail] = useState("");

  const [missingContext, setMissingContext] = useState<MissingContext[] | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    listJobs()
      .then(setJobs)
      .catch((err) => setJobsError(String(err)));
  }, []);

  function updateContextRow(index: number, field: keyof ContextRow, value: string) {
    setContextRows((rows) =>
      rows.map((row, i) => (i === index ? { ...row, [field]: value } : row))
    );
  }

  function addContextRow() {
    setContextRows((rows) => [...rows, { key: "", value: "" }]);
  }

  function buildContext(): Record<string, unknown> {
    const context: Record<string, unknown> = {};
    for (const row of contextRows) {
      if (row.key.trim() !== "" && row.value.trim() !== "") {
        context[row.key.trim()] = row.value;
      }
    }
    return context;
  }

  async function handleSubmit(acknowledgeMissingContext: boolean) {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const response = await submitJob({
        request: {
          ask,
          return_fields: returnFields
            .split(",")
            .map((f) => f.trim())
            .filter(Boolean),
          context: buildContext(),
          targets: targets
            .split(/[\n,]/)
            .map((t) => t.trim())
            .filter(Boolean),
        },
        notify_email: notifyEmail.trim() || null,
        acknowledge_missing_context: acknowledgeMissingContext,
      });

      if (response.status === "needs_context") {
        setMissingContext(response.brief.missing_context);
        // Turn each missing field straight into a fillable context row
        // (keyed by the field name the brief already resolved) instead of
        // making the user re-derive and type the key themselves.
        setContextRows((rows) => {
          const existingKeys = new Set(rows.map((r) => r.key));
          const additions = response.brief.missing_context
            .filter((m) => !existingKeys.has(m.field))
            .map((m) => ({ key: m.field, value: "" }));
          return [...rows, ...additions];
        });
        return;
      }

      setMissingContext(null);
      router.push(`/jobs/${response.job_id}`);
    } catch (err) {
      setSubmitError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <h1>Proxy</h1>
      <p className="subtitle">Submit calls, get back a ranked, transcript-backed result.</p>

      <section className="card form-card">
        <h2>New job</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit(false);
          }}
        >
          <label>
            Ask
            <input
              value={ask}
              onChange={(e) => setAsk(e.target.value)}
              placeholder="e.g. quote for front brake pad replacement"
              required
            />
          </label>

          <label>
            What do you want back? (comma-separated)
            <input
              value={returnFields}
              onChange={(e) => setReturnFields(e.target.value)}
              placeholder="e.g. price, whether it's mostly parts or labor, earliest availability"
              required
            />
          </label>

          <fieldset>
            <legend>Context (optional — helps avoid follow-up questions)</legend>
            {contextRows.map((row, i) => (
              <div className="context-row" key={i}>
                <input
                  placeholder="field name"
                  value={row.key}
                  onChange={(e) => updateContextRow(i, "key", e.target.value)}
                />
                <input
                  placeholder={row.key ? `value for ${row.key}` : "value"}
                  value={row.value}
                  onChange={(e) => updateContextRow(i, "value", e.target.value)}
                />
              </div>
            ))}
            <button type="button" onClick={addContextRow} className="secondary">
              + add field
            </button>
          </fieldset>

          <label>
            Targets (phone numbers, one per line)
            <textarea
              value={targets}
              onChange={(e) => setTargets(e.target.value)}
              placeholder={"+15550000001\n+15550000002"}
              required
            />
          </label>

          <label>
            Notify email (optional)
            <input
              type="email"
              value={notifyEmail}
              onChange={(e) => setNotifyEmail(e.target.value)}
            />
          </label>

          {missingContext && missingContext.length > 0 && (
            <div className="banner banner-warning">
              <strong>You&apos;ll likely be asked for context you haven&apos;t provided yet:</strong>
              <ul>
                {missingContext.map((m) => (
                  <li key={m.field}>{m.prompt}</li>
                ))}
              </ul>
              <p>Fill these in above, or submit anyway with partial context.</p>
              <button
                type="button"
                className="secondary"
                disabled={submitting}
                onClick={() => handleSubmit(true)}
              >
                Submit anyway
              </button>
            </div>
          )}

          {submitError && <p className="error">{submitError}</p>}

          <button type="submit" disabled={submitting}>
            {submitting ? "Submitting…" : "Submit job"}
          </button>
        </form>
      </section>

      <section className="card">
        <h2>Recent jobs</h2>
        {jobsError && <p className="error">{jobsError}</p>}
        {jobs.length === 0 && !jobsError && <p>No jobs yet.</p>}
        <table>
          <thead>
            <tr>
              <th>Ask</th>
              <th>Status</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.job_id}>
                <td>{job.ask}</td>
                <td>
                  <span className={`badge badge-${job.status}`}>
                    {STATE_LABEL[job.status]}
                  </span>
                </td>
                <td>{new Date(job.created_at).toLocaleString()}</td>
                <td>
                  <Link href={`/jobs/${job.job_id}`}>View</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
