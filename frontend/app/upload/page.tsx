"use client";

import { CheckCircle2, FileAudio, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { UploadTarget } from "@/lib/types";

async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function uploadWithProgress(xhr: XMLHttpRequest, body: XMLHttpRequestBodyInit) {
    return new Promise<void>((resolve, reject) => {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          setProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
      xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error("Upload failed")));
      xhr.onerror = () => reject(new Error("Upload failed"));
      xhr.send(body);
    });
  }

  // Direct API upload (multipart) — used when no S3 is configured, or as a
  // fallback when the S3 presigned PUT fails (e.g. LocalStack down in dev).
  function directUpload(meetingId: string, fileToUpload: File) {
    const formData = new FormData();
    formData.append("file", fileToUpload);
    const xhr = new XMLHttpRequest();
    xhr.open(
      "POST",
      `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"}/meetings/${meetingId}/upload`
    );
    xhr.setRequestHeader("Authorization", `Bearer ${sessionStorage.getItem("meetai_access") || ""}`);
    return uploadWithProgress(xhr, formData);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return setError("Choose an audio or video recording.");
    setBusy(true);
    setError("");

    const data = new FormData(event.currentTarget);

    try {
      // Step 1: Create the meeting record (+ S3 presigned URL when configured)
      const meeting = await api<UploadTarget>("/meetings", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          title: data.get("title"),
          meeting_date: data.get("meeting_date") || null,
          project: data.get("project") || null,
          department: data.get("department") || null,
          filename: file.name,
          content_type: file.type || "audio/mpeg",
          source: "WEB_UPLOAD",
        }),
      });

      if (meeting.upload_url) {
        try {
          // Step 2a: S3 path — PUT straight to the presigned URL (durable on
          // hosting with ephemeral disks, e.g. Render free), then finalize.
          const xhr = new XMLHttpRequest();
          xhr.open("PUT", meeting.upload_url);
          for (const [key, value] of Object.entries(meeting.upload_headers)) {
            xhr.setRequestHeader(key, value);
          }
          await uploadWithProgress(xhr, file);
          const checksum = await sha256(file);
          await api(`/meetings/${meeting.meeting_id}/recordings/${meeting.recording_id}/complete`, {
            method: "POST",
            body: JSON.stringify({ size_bytes: file.size, checksum_sha256: checksum }),
          });
        } catch {
          // S3 unreachable (LocalStack down in dev, expired URL, network) —
          // fall back to the direct API upload so the recording still lands.
          await directUpload(meeting.meeting_id, file);
        }
      } else {
        // Step 2b: Direct API upload (no S3 configured — dev mode).
        await directUpload(meeting.meeting_id, file);
      }

      router.push(`/meetings/${meeting.meeting_id}`);
    } catch (caught) {
      setError(caught instanceof ApiError || caught instanceof Error ? caught.message : "Upload failed");
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <PageHeader
        title="Add recording"
        description="Upload an audio or video file for transcription and indexing."
      />
      <form className="content-form" onSubmit={submit}>
        <section className="form-section">
          <h2>Meeting details</h2>
          <div className="form-grid">
            <label className="span-2">
              Meeting title
              <input name="title" required maxLength={300} placeholder="Weekly product review" />
            </label>
            <label>
              Meeting date
              <input name="meeting_date" type="date" />
            </label>
            <label>
              Project
              <input name="project" maxLength={200} placeholder="Project name" />
            </label>
            <label>
              Department
              <input name="department" maxLength={200} placeholder="Department" />
            </label>
          </div>
        </section>
        <section className="form-section">
          <h2>Recording</h2>
          <label className={`file-drop ${file ? "has-file" : ""}`}>
            <input
              type="file"
              accept="audio/*,video/*"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            {file ? (
              <>
                <CheckCircle2 size={28} />
                <strong>{file.name}</strong>
                <span>{(file.size / 1024 / 1024).toFixed(1)} MB</span>
              </>
            ) : (
              <>
                <UploadCloud size={30} />
                <strong>Choose a recording</strong>
                <span>Audio or video files supported</span>
              </>
            )}
          </label>
          {busy && (
            <div className="progress-row">
              <FileAudio size={18} />
              <div>
                <span>Uploading recording</span>
                <progress max={100} value={progress} />
              </div>
              <strong>{progress}%</strong>
            </div>
          )}
        </section>
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="form-actions">
          <button className="button primary" disabled={busy || !file}>
            <UploadCloud size={17} />
            {busy ? "Uploading..." : "Upload and process"}
          </button>
        </div>
      </form>
    </AppShell>
  );
}
