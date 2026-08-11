export interface UploadTarget {
  meeting_id: string;
  recording_id: string;
  upload_url: string;
  upload_headers: Record<string, string>;
  expires_in: number;
}

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

export interface SearchResultMetadata {
  project: string | null;
  department: string | null;
  cleaning_version: string | null;
  chunk_strategy_version: string | null;
  embedding_model: string | null;
  matched_type: "TURN" | "CONTEXT" | null;
  dense_score: number | null;
  turn_span: [number | null, number | null] | null;
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
  metadata: SearchResultMetadata;
}

export interface Citation {
  marker: string;
  chunk_id: string;
  meeting_id: string;
  meeting_title: string;
  start_ms: number;
  end_ms: number;
  text: string;
}

export type ChatRole = "USER" | "ASSISTANT";

export interface ChatSession {
  id: string;
  meeting_id: string;
  title: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: ChatRole;
  content: string;
  citations: Citation[];
  evidence_sufficient: boolean | null;
  created_at: string;
}

export interface ChatMessageListResponse {
  items: ChatMessage[];
  total: number;
  has_more: boolean;
  limit: number;
  offset: number;
}

