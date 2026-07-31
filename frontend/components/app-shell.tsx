"use client";

import {
  AudioLines,
  BriefcaseBusiness,
  LogOut,
  Menu,
  Plus,
  Search,
  Settings,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, authStore, refreshAccess } from "@/lib/api";

const navigation = [
  { href: "/", label: "Meetings", icon: AudioLines },
  { href: "/search", label: "Search & ask", icon: Search },
  { href: "/upload", label: "Add recording", icon: Plus },
  { href: "/admin/jobs", label: "Processing jobs", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    async function restoreSession() {
      if (!authStore.accessToken && !(await refreshAccess())) {
        router.replace("/login");
        return;
      }
      setReady(true);
    }
    void restoreSession();
  }, [router]);

  if (!ready) return <div className="center-state">Loading workspace...</div>;

  async function signOut() {
    await api<void>("/auth/logout", { method: "POST", body: JSON.stringify({}) }).catch(() => undefined);
    authStore.clear();
    router.replace("/login");
  }

  return (
    <div className="app-frame">
      <header className="mobile-header">
        <Link href="/" className="brand"><BriefcaseBusiness size={20} /> MeetAI</Link>
        <button className="icon-button" onClick={() => setMobileOpen(true)} aria-label="Open menu">
          <Menu size={20} />
        </button>
      </header>
      {mobileOpen && <button className="nav-scrim" onClick={() => setMobileOpen(false)} aria-label="Close menu" />}
      <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-head">
          <Link href="/" className="brand"><BriefcaseBusiness size={21} /> MeetAI</Link>
          <button className="icon-button mobile-only" onClick={() => setMobileOpen(false)} aria-label="Close menu"><X size={20} /></button>
        </div>
        <nav className="primary-nav" aria-label="Main navigation">
          {navigation.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link key={item.href} href={item.href} className={active ? "nav-link active" : "nav-link"} onClick={() => setMobileOpen(false)}>
                <Icon size={18} /> {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <button className="nav-link" onClick={() => void signOut()}><LogOut size={18} /> Sign out</button>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}
