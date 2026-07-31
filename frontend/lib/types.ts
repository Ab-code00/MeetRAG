export type MeetingStatus =
  | "PENDING"
  | "TRANSCRIBING"
  | "TRANSCRIBED"
  | "CLEANING"
  | "CLEANED"
  | "CHUNKING"
  | "CHUNKED"
  | "EMBEDDING"
  | "INDEXING"
  | "READY"
  | "FAILED";

export interface Meeting {
  id: string;
  title: string;
  meeting_date: string | null;
  project: string | null;
  department: string | null;
  source: string;
  status: MeetingStatus;
  duration_ms: number | null;
  failure_reason: string | null;
  created_at: string;
}

export interface SearchResult {
  chunk_id: string;
  clean_chunk_id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string | null;
  start_ms: number;
  end_ms: number;
  speaker_set: string[];
  text: string;
  score: number;
  metadata: Record<string, string | null>;
}

