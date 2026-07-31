"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MessageCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { MeetingChat } from "@/components/meeting-chat";
import { PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import type { Meeting } from "@/lib/types";

export default function MeetingChatPage() {
  const { id } = useParams<{ id: string }>();
  const meeting = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api<Meeting>(`/meetings/${id}`),
  });

  return (
    <AppShell>
      <PageHeader
        title={`Chat · ${meeting.data?.title ?? "Meeting"}`}
        description="Ask questions — answers are grounded only in this meeting's transcript."
        actions={
          <Link className="button secondary" href={`/meetings/${id}`}>
            <ArrowLeft size={16} /> Back to meeting
          </Link>
        }
      />
      <div className="chat-page-note">
        <MessageCircle size={16} />
        <span>Chat history is saved per user and persists across visits.</span>
      </div>
      <div className="chat-page-full">
        <MeetingChat meetingId={id} />
      </div>
    </AppShell>
  );
}
