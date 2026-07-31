"use client";

import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { StatusPill } from "@/components/status-pill";
import { PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

type Job = { id: string; stage: string; status: string; retry_count: number; max_retries: number; latency_ms: number | null; failure_reason: string | null; created_at: string };
type Jobs = { items: Job[]; total: number };

export default function JobsPage() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api<Jobs>("/admin/jobs"), refetchInterval: 5000 });
  async function retry(id: string) { await api(`/admin/jobs/${id}/retry`, { method: "POST" }); await jobs.refetch(); }
  return <AppShell>
    <PageHeader title="Processing jobs" description="Inspect pipeline execution, failures, and retries." />
    {jobs.isLoading && <div className="center-state">Loading jobs...</div>}
    {jobs.isError && <div className="error-banner">Admin access is required to inspect processing jobs.</div>}
    {jobs.data && <div className="table-wrap"><table><thead><tr><th>Stage</th><th>Started</th><th>Latency</th><th>Retries</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>
      {jobs.data.items.map((job) => <tr key={job.id}><td><span className="table-primary">{job.stage.replaceAll("_", " ")}</span>{job.failure_reason && <small className="failure-text" title={job.failure_reason}>{job.failure_reason}</small>}</td><td>{new Date(job.created_at).toLocaleString()}</td><td>{job.latency_ms ? `${(job.latency_ms / 1000).toFixed(1)}s` : "-"}</td><td>{job.retry_count} / {job.max_retries}</td><td><StatusPill status={job.status} /></td><td>{["FAILED", "DEAD_LETTERED"].includes(job.status) && <button className="icon-button" title="Retry job" onClick={() => retry(job.id)}><RotateCcw size={16} /></button>}</td></tr>)}
    </tbody></table></div>}
  </AppShell>;
}

