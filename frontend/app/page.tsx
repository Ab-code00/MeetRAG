"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { StatusPill } from "@/components/status-pill";
import { EmptyState, PageHeader, formatTime } from "@/components/ui";
import { api } from "@/lib/api";
import type { Meeting } from "@/lib/types";

type MeetingList = { items: Meeting[]; total: number };

export default function MeetingsPage() {
  const meetings = useQuery({
    queryKey: ["meetings"],
    queryFn: () => api<MeetingList>("/meetings"),
    refetchInterval: (query) => query.state.data?.items.some((item) => !["READY", "FAILED"].includes(item.status)) ? 5000 : false,
  });
  return (
    <AppShell>
      <PageHeader title="Meetings" description="Recorded conversations and their processing state." actions={<Link className="button primary" href="/upload"><Plus size={17} /> Add recording</Link>} />
      <div className="summary-strip">
        <div><span>Total meetings</span><strong>{meetings.data?.total ?? 0}</strong></div>
        <div><span>Ready to search</span><strong>{meetings.data?.items.filter((item) => item.status === "READY").length ?? 0}</strong></div>
        <div><span>Processing</span><strong>{meetings.data?.items.filter((item) => !["READY", "FAILED"].includes(item.status)).length ?? 0}</strong></div>
        <div><span>Needs attention</span><strong>{meetings.data?.items.filter((item) => item.status === "FAILED").length ?? 0}</strong></div>
      </div>
      {meetings.isLoading && <div className="center-state">Loading meetings...</div>}
      {meetings.isError && <div className="error-banner">Could not load meetings.<button onClick={() => meetings.refetch()}><RefreshCw size={15} /> Retry</button></div>}
      {meetings.data?.items.length === 0 && <EmptyState title="No meetings yet" detail="Upload a recording to create searchable meeting knowledge." action={<Link className="button primary" href="/upload"><Plus size={17} /> Add recording</Link>} />}
      {!!meetings.data?.items.length && <div className="table-wrap"><table>
        <thead><tr><th>Meeting</th><th>Date</th><th>Project</th><th>Duration</th><th>Status</th><th><span className="sr-only">Open</span></th></tr></thead>
        <tbody>{meetings.data.items.map((meeting) => <tr key={meeting.id}>
          <td><Link className="table-primary" href={`/meetings/${meeting.id}`}>{meeting.title}</Link><small>{meeting.department ?? "No department"}</small></td>
          <td>{meeting.meeting_date ? new Date(`${meeting.meeting_date}T00:00:00`).toLocaleDateString() : "Not set"}</td>
          <td>{meeting.project ?? "Not set"}</td>
          <td>{meeting.duration_ms ? formatTime(meeting.duration_ms) : "-"}</td>
          <td><StatusPill status={meeting.status} /></td>
          <td><Link className="icon-button" href={`/meetings/${meeting.id}`} title="Open meeting"><ArrowRight size={17} /></Link></td>
        </tr>)}</tbody>
      </table></div>}
    </AppShell>
  );
}

