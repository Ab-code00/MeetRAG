"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronUp, MessageCircle, Plus, Send, Trash2 } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, streamChat } from "@/lib/api";
import { linkCitations, Markdown } from "@/components/markdown";
import { formatTime } from "@/components/ui";
import type { ChatMessage, ChatMessageListResponse, ChatSession } from "@/lib/types";

const PAGE_LIMIT = 50;

type ChatListResponse = { items: ChatSession[]; total: number };

function relativeTime(value: string): string {
  const elapsed = Date.now() - new Date(value).getTime();
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "yesterday" : `${days}d ago`;
}

export function MeetingChat({ meetingId }: { meetingId: string }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [askError, setAskError] = useState("");
  // Live streaming turn: the optimistic user bubble + the assistant bubble
  // that fills in as SSE deltas arrive. Cleared on done/error.
  const [stream, setStream] = useState<{
    sessionId: string;
    question: string;
    text: string;
    status: string;
  } | null>(null);
  const isStreaming = stream !== null;
  // Pagination: `offset` is the newest-unfetched boundary; fetched pages are
  // kept in `pages` (keyed by offset, newest-first within each page) so the
  // latest page stays available while older pages stream in.
  const [offset, setOffset] = useState(0);
  const [pages, setPages] = useState<Record<number, ChatMessage[]>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  // Abort any in-flight stream when the component unmounts.
  useEffect(() => {
    return () => streamAbortRef.current?.abort();
  }, []);

  const sessions = useQuery({
    queryKey: ["chats", meetingId],
    queryFn: () => api<ChatListResponse>(`/meetings/${meetingId}/chats`),
  });
  const messages = useQuery({
    queryKey: ["chat-messages", selectedId, offset],
    queryFn: () =>
      api<ChatMessageListResponse>(
        `/chats/${selectedId}/messages?limit=${PAGE_LIMIT}&offset=${offset}`,
      ),
    enabled: Boolean(selectedId),
  });

  // Auto-select the most recent session once sessions load.
  useEffect(() => {
    if (!selectedId && sessions.data?.items.length) {
      setSelectedId(sessions.data.items[0].id);
    }
  }, [sessions.data, selectedId]);

  // Reset pagination when switching sessions.
  useEffect(() => {
    setOffset(0);
    setPages({});
  }, [selectedId]);

  // Store each fetched page (keyed by its offset) as it arrives.
  useEffect(() => {
    if (messages.data && messages.data.items.length > 0) {
      setPages((prev) => ({ ...prev, [messages.data.offset]: messages.data.items }));
    }
  }, [messages.data]);

  // Scroll to the newest message when the latest page refreshes.
  useEffect(() => {
    if (offset === 0 && messages.data) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
    }
  }, [messages.data, offset]);

  // Follow the text as it streams in.
  useEffect(() => {
    if (stream) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
    }
  }, [stream]);

  const createSession = useMutation({
    mutationFn: () =>
      api<ChatSession>(`/meetings/${meetingId}/chats`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: (session) => {
      setSelectedId(session.id);
      queryClient.invalidateQueries({ queryKey: ["chats", meetingId] });
    },
  });

  const deleteSession = useMutation({
    mutationFn: (sessionId: string) =>
      api<void>(`/chats/${sessionId}`, { method: "DELETE" }),
    onSuccess: (_data, sessionId) => {
      setSelectedId(null);
      queryClient.removeQueries({ queryKey: ["chat-messages", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["chats", meetingId] });
    },
  });

  function startStream(sessionId: string, rawQuery: string) {
    const query = rawQuery.trim();
    setQuestion("");
    setAskError("");
    setStream({ sessionId, question: query, text: "", status: "Thinking…" });
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    void streamChat(
      `/chats/${sessionId}/messages/stream`,
      { query },
      {
        onStatus: (status) =>
          setStream((current) => (current ? { ...current, status } : current)),
        onDelta: (text) =>
          setStream((current) =>
            current ? { ...current, text: current.text + text } : current,
          ),
        onDone: () => {
          setStream(null);
          setOffset(0);
          setPages({});
          queryClient.invalidateQueries({ queryKey: ["chat-messages", sessionId] });
          queryClient.invalidateQueries({ queryKey: ["chats", meetingId] });
        },
        onError: (message) => {
          // Clear the stream so isStreaming flips false and the composer/session
          // controls re-enable; the message surfaces via the askError banner.
          setAskError(message);
          setStream(null);
        },
      },
      controller.signal,
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || !question.trim() || isStreaming) return;
    startStream(selectedId, question);
  }

  function loadEarlier() {
    if (messages.data?.has_more && !messages.isFetching) {
      setOffset((current) => current + PAGE_LIMIT);
    }
  }

  // Combine fetched pages oldest-first: higher offsets are older and display first.
  const visible: ChatMessage[] = Object.keys(pages)
    .map(Number)
    .sort((a, b) => b - a)
    .flatMap((pageOffset) => pages[pageOffset].slice().reverse());

  const hasMore = Boolean(messages.data?.has_more);
  const currentSession = sessions.data?.items.find((item) => item.id === selectedId) ?? null;
  const isEmpty = selectedId === null || (visible.length === 0 && !messages.isLoading && !stream);

  return (
    <section className="chat-panel" aria-label="Chat with this meeting">
      <aside className="chat-side">
        <div className="chat-side-head">
          <h3>Chat sessions</h3>
          <button
            className="chat-new"
            onClick={() => createSession.mutate()}
            disabled={createSession.isPending || isStreaming}
          >
            <Plus size={14} /> New
          </button>
        </div>
        <div className="chat-sessions">
          {sessions.data?.items.length === 0 && (
            <div className="chat-empty">No chats yet — start a conversation.</div>
          )}
          {sessions.data?.items.map((session) => (
            <button
              key={session.id}
              className={`chat-session ${session.id === selectedId ? "active" : ""}`}
              onClick={() => setSelectedId(session.id)}
              disabled={isStreaming}
            >
              <strong>{session.title ?? "Untitled chat"}</strong>
              <small>
                {session.message_count} message{session.message_count === 1 ? "" : "s"} ·{" "}
                {relativeTime(session.updated_at)}
              </small>
            </button>
          ))}
        </div>
      </aside>

      <div className="chat-main">
        <div className="chat-messages" ref={scrollRef}>
          {messages.isLoading && selectedId && visible.length === 0 && (
            <div className="chat-empty">Loading...</div>
          )}
          {!messages.isLoading && isEmpty && (
            <div className="chat-empty">
              <MessageCircle size={26} />
              <p>Ask anything about this meeting. Answers are grounded only in this meeting&apos;s transcript.</p>
            </div>
          )}
          {hasMore && (
            <button
              className="chat-load-more"
              onClick={loadEarlier}
              disabled={messages.isFetching}
            >
              <ChevronUp size={14} />
              {messages.isFetching ? "Loading..." : "Load earlier messages"}
            </button>
          )}
          {visible.map((message, index) => (
            <div
              key={message.id}
              className={`chat-bubble ${message.role.toLowerCase()} ${index === visible.length - 1 ? "new" : ""}`}
            >
              {message.role === "ASSISTANT" ? (
                <Markdown>{linkCitations(message.content, message.citations)}</Markdown>
              ) : (
                <p>{message.content}</p>
              )}
              {message.role === "ASSISTANT" && message.citations.length > 0 && (
                <div className="chat-cites">
                  {message.citations.map((citation) => (
                    <Link
                      key={citation.marker}
                      href={`/meetings/${citation.meeting_id}#chunk-${citation.chunk_id}`}
                    >
                      <span className="chat-cite-marker">[{citation.marker}]</span>
                      {citation.meeting_title} · {formatTime(citation.start_ms)}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}
          {stream && (
            <>
              <div className="chat-bubble user new">
                <p>{stream.question}</p>
              </div>
              <div className="chat-bubble assistant streaming new">
                {stream.text ? (
                  <Markdown>{linkCitations(stream.text, [])}</Markdown>
                ) : (
                  <span className="chat-stream-status">{stream.status}</span>
                )}
                <span className="chat-cursor" aria-hidden="true" />
              </div>
            </>
          )}
        </div>
        <form className="chat-composer" onSubmit={submit}>
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={
              currentSession ? "Ask about this meeting..." : "Start a chat session first"
            }
            disabled={!selectedId || isStreaming}
            minLength={2}
            maxLength={2000}
            required
          />
          <button
            className="button primary"
            disabled={!selectedId || isStreaming || !question.trim()}
          >
            {isStreaming ? "Working..." : "Send"}
            <Send size={16} />
          </button>
        </form>
        {askError && !stream && <div className="chat-error form-error">{askError}</div>}
        {currentSession && (
          <button
            className="chat-delete"
            onClick={() => deleteSession.mutate(currentSession.id)}
            disabled={deleteSession.isPending}
          >
            <Trash2 size={14} /> Delete this chat
          </button>
        )}
      </div>
    </section>
  );
}
