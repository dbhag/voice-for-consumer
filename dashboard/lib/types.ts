export type TerminalState = "got_info" | "couldnt_reach" | "refused";
export type CompletionLevel = "full" | "partial";

export type FieldResult = {
  value: unknown;
  source_span: string | null;
  confidence: number | null;
  reason: string | null;
};

export type TranscriptTurn = {
  turn_id: number;
  speaker: "agent" | "human" | "ivr";
  text: string;
  timestamp: string;
};

export type CallResult = {
  target: string;
  terminal_state: TerminalState;
  completion_level: CompletionLevel | null;
  reach_failure: string | null;
  refusal_reason: string | null;
  fields: Record<string, FieldResult>;
  transcript: TranscriptTurn[];
  from_cache: boolean;
  call_minutes: number;
  started_at: string;
  ended_at: string | null;
};

export type RequestPayload = {
  ask: string;
  return_fields: string[];
  context: Record<string, unknown>;
  boundaries?: { read_only: boolean; do_not_share: string[] };
  targets: string[];
};

export type MissingContext = {
  field: string;
  prompt: string;
};

export type PreCallBrief = {
  primary_question: string;
  return_fields: string[];
  likely_follow_ups: string[];
  missing_context: MissingContext[];
};

export type SubmitJobResponse =
  | { status: "needs_context"; brief: PreCallBrief }
  | { status: "queued"; job_id: string };

export type JobStatus = "queued" | "running" | "done" | "failed";

export type JobDetail = {
  job_id: string;
  status: JobStatus;
  error: string | null;
  request: RequestPayload | null;
  results: CallResult[] | null;
};

export type JobSummary = {
  job_id: string;
  ask: string;
  status: JobStatus;
  created_at: string;
};
