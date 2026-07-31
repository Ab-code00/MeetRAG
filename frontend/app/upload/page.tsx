"use client";

import { CheckCircle2, FileAudio, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return setError("Choose an audio or video recording.");
    setBusy(true);
    setError("");

    const data = new FormData(event.currentTarget);

    try {
      // Step 1: Create the meeting record
      const meeting = await api<{ meeting_id: string; recording_id: string }>("/meetings", {
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

      // Step 2: Upload the file directly (multipart) — pipeline auto-starts
      const formData = new FormData();
      formData.append("file", file);

      // Use XMLHttpRequest for upload progress tracking
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open(
          "POST",
          `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"}/meetings/${meeting.meeting_id}/upload`
        );
        xhr.setRequestHeader("Authorization", `Bearer ${sessionStorage.getItem("meetai_access") || ""}`);
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            setProgress(Math.round((event.loaded / event.total) * 100));
          }
        };
        xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error("Upload failed")));
        xhr.onerror = () => reject(new Error("Upload failed"));
        xhr.send(formData);
      });

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
