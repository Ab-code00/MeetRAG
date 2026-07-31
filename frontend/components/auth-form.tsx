"use client";

import { ArrowRight, BriefcaseBusiness } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { ApiError, authenticate } from "@/lib/api";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string, string>;
    try {
      await authenticate(mode, data);
      router.replace("/");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not authenticate");
    } finally {
      setBusy(false);
    }
  }

  const register = mode === "register";
  return (
    <main className="auth-layout">
      <section className="auth-panel">
        <div className="auth-brand"><BriefcaseBusiness size={22} /> MeetAI</div>
        <div className="auth-heading">
          <h1>{register ? "Create your workspace" : "Sign in to your workspace"}</h1>
          <p>{register ? "Set up your organization and owner account." : "Access transcripts, evidence, and grounded answers."}</p>
        </div>
        <form onSubmit={submit} className="form-stack">
          {register && <>
            <label>Organization name<input name="organization_name" required minLength={2} autoComplete="organization" /></label>
            <label>Workspace slug<input name="organization_slug" required minLength={2} pattern="[a-z0-9-]+" placeholder="acme-team" /></label>
            <label>Your name<input name="name" required minLength={2} autoComplete="name" /></label>
          </>}
          {!register && <label>Workspace slug<input name="organization_slug" required autoComplete="organization" /></label>}
          <label>Email address<input name="email" type="email" required autoComplete="email" /></label>
          <label>Password<input name="password" type="password" required minLength={12} autoComplete={register ? "new-password" : "current-password"} /></label>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="button primary full" disabled={busy}>{busy ? "Please wait..." : register ? "Create workspace" : "Sign in"}<ArrowRight size={17} /></button>
        </form>
        <p className="auth-switch">{register ? "Already have a workspace?" : "New to MeetAI?"} <Link href={register ? "/login" : "/register"}>{register ? "Sign in" : "Create one"}</Link></p>
      </section>
    </main>
  );
}

