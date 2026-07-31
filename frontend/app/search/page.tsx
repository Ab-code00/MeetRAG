"use client";

import { ExternalLink, Search, Send } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { linkCitations, Markdown } from "@/components/markdown";
import { PageHeader, formatTime } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { SearchResult } from "@/lib/types";

type SearchResponse = { results: SearchResult[] };
type AskResponse = { answer: string; evidence_sufficient: boolean; citations: { marker: string; chunk_id: string; meeting_id: string; meeting_title: string; start_ms: number; end_ms: number; text: string }[] };

export default function SearchPage() {
  const [mode, setMode] = useState<"ask" | "search">("ask");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | AskResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setResult(null);
    try { setResult(await api(mode === "ask" ? "/ask" : "/search", { method: "POST", body: JSON.stringify({ query, filters: {} }) })); }
    catch (caught) { setError(caught instanceof ApiError ? caught.message : "Request failed"); }
    finally { setBusy(false); }
  }
  const askResult = mode === "ask" ? result as AskResponse | null : null;
  const searchResult = mode === "search" ? result as SearchResponse | null : null;
  return <AppShell>
    <PageHeader title="Search & ask" description="Find transcript evidence or generate an answer grounded in it." />
    <div className="segmented wide" role="tablist"><button className={mode === "ask" ? "selected" : ""} onClick={() => { setMode("ask"); setResult(null); }}>Ask a question</button><button className={mode === "search" ? "selected" : ""} onClick={() => { setMode("search"); setResult(null); }}>Search evidence</button></div>
    <form className="search-box" onSubmit={submit}><Search size={20} /><input value={query} onChange={(event) => setQuery(event.target.value)} required minLength={2} placeholder={mode === "ask" ? "What decisions were made about the launch?" : "Search meeting transcripts"} /><button className="button primary" disabled={busy}>{busy ? "Working..." : mode === "ask" ? "Ask" : "Search"}<Send size={16} /></button></form>
    {error && <div className="form-error">{error}</div>}
    {askResult && <section className="answer-section"><div className="answer-heading"><span>Grounded answer</span><small>{askResult.evidence_sufficient ? `${askResult.citations.length} cited sources` : "Insufficient evidence"}</small></div><div className="answer-text"><Markdown>{linkCitations(askResult.answer, askResult.citations)}</Markdown></div>
      {askResult.citations.length > 0 && <div className="evidence-list"><h2>Sources</h2>{askResult.citations.map((citation) => <article className="evidence-row" key={citation.marker}><span className="citation-marker">{citation.marker}</span><div><div className="evidence-meta"><Link href={`/meetings/${citation.meeting_id}#chunk-${citation.chunk_id}`}>{citation.meeting_title} <ExternalLink size={13} /></Link><span>{formatTime(citation.start_ms)} - {formatTime(citation.end_ms)}</span></div><p>{citation.text}</p></div></article>)}</div>}
    </section>}
    {searchResult && <section className="evidence-list search-results"><h2>{searchResult.results.length} results</h2>{searchResult.results.map((item) => <article className="evidence-row" key={item.chunk_id}><span className="score">{Math.round(item.score * 100)}%</span><div><div className="evidence-meta"><Link href={`/meetings/${item.meeting_id}#chunk-${item.chunk_id}`}>{item.meeting_title} <ExternalLink size={13} /></Link><span>{formatTime(item.start_ms)} - {formatTime(item.end_ms)}</span></div><p>{item.text}</p><small>{item.speaker_set.join(", ")}</small></div></article>)}</section>}
  </AppShell>;
}

