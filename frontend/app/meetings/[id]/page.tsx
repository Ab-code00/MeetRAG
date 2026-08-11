"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Calendar, Clock, MessageCircle, RefreshCw, Users } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { MeetingChat } from "@/components/meeting-chat";
import { StatusPill } from "@/components/status-pill";
import { PageHeader, formatTime } from "@/components/ui";
import { api } from "@/lib/api";
import type { Meeting } from "@/lib/types";

type Transcript = {
  raw_text: string | null;
  stt_model: string | null;
  segments: { id: string; start_ms: number; end_ms: number; speaker: string | null; text: string }[];
  clean_chunks: { chunk_id: string; start_ms: number; end_ms: number; speaker_set: string[]; cleaned_text: string; cleaning_version: string; chunk_strategy_version: string; chunk_type: string }[];
};
type Detail = Meeting & { recordings: { id: string; original_filename: string; size_bytes: number | null }[] };

export default function MeetingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [view, setView] = useState<"clean" | "raw">("clean");
  const meeting = useQuery({ queryKey: ["meeting", id], queryFn: () => api<Detail>(`/meetings/${id}`), refetchInterval: 5000 });
  const transcript = useQuery({ queryKey: ["transcript", id], queryFn: () => api<Transcript>(`/meetings/${id}/transcript`), refetchInterval: meeting.data?.status === "READY" ? false : 5000 });

  async function reprocess() {
    await api(`/meetings/${id}/reprocess`, { method: "POST", body: JSON.stringify({ from_stage: "CLEAN" }) });
    await meeting.refetch();
  }
  if (meeting.isLoading) return <AppShell><div className="center-state">Loading meeting...</div></AppShell>;
  if (!meeting.data) return <AppShell><div className="error-banner">Meeting could not be loaded.</div></AppShell>;
  const item = meeting.data;
  return <AppShell>
    <PageHeader title={item.title} description={item.project ?? "No project assigned"} actions={<><StatusPill status={item.status} /><button className="button secondary" onClick={reprocess}><RefreshCw size={16} /> Reprocess</button></>} />
    <div className="metadata-band">
      <span><Calendar size={16} />{item.meeting_date ? new Date(`${item.meeting_date}T00:00:00`).toLocaleDateString() : "Date not set"}</span>
      <span><Clock size={16} />{item.duration_ms ? formatTime(item.duration_ms) : "Duration pending"}</span>
      <span><Users size={16} />{item.department ?? "Department not set"}</span>
    </div>
    {item.failure_reason && <div className="error-banner"><AlertTriangle size={18} /><div><strong>Processing failed</strong><p>{item.failure_reason}</p></div></div>}
    <div className="section-toolbar"><div><h2>Transcript</h2><p>{transcript.data?.stt_model ? `Transcribed with ${transcript.data.stt_model}` : "Transcript will appear after processing."}</p></div>
      <div className="segmented" role="tablist"><button className={view === "clean" ? "selected" : ""} onClick={() => setView("clean")}>Cleaned</button><button className={view === "raw" ? "selected" : ""} onClick={() => setView("raw")}>Raw source</button></div>
    </div>
    {transcript.isLoading && <div className="center-state">Loading transcript...</div>}
    {transcript.data && view === "clean" && <div className="transcript-list">
      {transcript.data.clean_chunks.length === 0 && <div className="empty-inline">Cleaned chunks are not available yet.</div>}
      {transcript.data.clean_chunks.map((chunk) => <article className="transcript-row" key={chunk.chunk_id} id={`chunk-${chunk.chunk_id}`}>
        <button className="timestamp" title="Jump to timestamp">{formatTime(chunk.start_ms)}</button>
        <div><div className="speaker-line">{chunk.speaker_set.join(", ")}</div><p>{chunk.cleaned_text}</p><small>{chunk.cleaning_version} / {chunk.chunk_strategy_version}</small></div>
      </article>)}
    </div>}
    {transcript.data && view === "raw" && <div className="transcript-list raw">
      {transcript.data.segments.length === 0 && <div className="empty-inline">Raw transcript is not available yet.</div>}
      {transcript.data.segments.map((segment) => <article className="transcript-row" key={segment.id}><span className="timestamp">{formatTime(segment.start_ms)}</span><div><div className="speaker-line">{segment.speaker ?? "Unknown speaker"}</div><p>{segment.text}</p></div></article>)}
    </div>}
    <div className="section-toolbar chat-toolbar"><div><h2>Chat with this meeting</h2><p>Ask questions — answers are grounded only in this meeting&apos;s transcript.</p></div><Link className="button secondary" href={`/meetings/${id}/chat`}><MessageCircle size={16} /> Open full chat</Link></div>
    <MeetingChat meetingId={id} />
  </AppShell>;
}

