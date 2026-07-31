import type { MeetingStatus } from "@/lib/types";

export function StatusPill({ status }: { status: MeetingStatus | string }) {
  const tone = status === "READY" || status === "SUCCEEDED"
    ? "success"
    : status === "FAILED" || status === "DEAD_LETTERED"
      ? "danger"
      : status === "PENDING"
        ? "neutral"
        : "processing";
  return <span className={`status-pill ${tone}`}><span aria-hidden="true" />{status.replaceAll("_", " ").toLowerCase()}</span>;
}

