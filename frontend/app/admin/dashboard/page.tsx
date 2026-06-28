"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface SessionRow {
  id: string;
  first_name: string;
  form_id: string;
  patient_external_id: string | null;
  status: string;
  mock_mode: boolean;
  archived: boolean;
  answer_count: number;
  has_pdf: boolean;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

interface Stats {
  total: number;
  completed: number;
  active: number;
  ready_for_review: number;
  orphan: number;
  archived: number;
}

type Filter = "all" | "active" | "ready_for_review" | "completed" | "orphan" | "archived";

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: "bg-blue-100 text-blue-700",
    ready_for_review: "bg-amber-100 text-amber-700",
    completed: "bg-green-100 text-green-700",
    abandoned: "bg-gray-100 text-gray-500",
  };
  const label = status === "ready_for_review" ? "ready" : status;
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${map[status] ?? "bg-gray-100 text-gray-600"}`}>
      {label}
    </span>
  );
}

export default function AdminDashboardPage() {
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);

  function authHeaders(): HeadersInit {
    return { Authorization: `Bearer ${localStorage.getItem("admin_token") ?? ""}`, "Content-Type": "application/json" };
  }

  const load = useCallback(async () => {
    const token = localStorage.getItem("admin_token");
    if (!token) { router.replace("/admin"); return; }

    setLoading(true);
    setError(null);
    try {
      // Fetch archived too so the Archived tab works; non-archived tabs filter them out.
      const res = await fetch(`${API}/api/admin/dashboard?include_archived=true`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        localStorage.removeItem("admin_token");
        router.replace("/admin");
        return;
      }
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setStats(data.stats);
      setSessions(data.sessions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  function handleLogout() {
    localStorage.removeItem("admin_token");
    router.push("/admin");
  }

  async function mutate(path: string, method: string) {
    setBusy(path);
    setError(null);
    try {
      const res = await fetch(`${API}${path}`, { method, headers: authHeaders() });
      if (res.status === 401) { localStorage.removeItem("admin_token"); router.replace("/admin"); return; }
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }
  const archive = (id: string) => mutate(`/api/admin/sessions/${id}/archive`, "POST");
  const unarchive = (id: string) => mutate(`/api/admin/sessions/${id}/unarchive`, "POST");
  const remove = (id: string) => {
    if (confirm("Permanently delete this application and ALL its data? This cannot be undone.")) {
      mutate(`/api/admin/sessions/${id}`, "DELETE");
    }
  };
  const archiveOrphans = () => {
    if (confirm("Archive every abandoned application (0 answers)? You can still find them under Archived.")) {
      mutate(`/api/admin/sessions/archive-orphans`, "POST");
    }
  };

  const isOrphan = (s: SessionRow) => !s.archived && s.status === "active" && s.answer_count === 0;
  const visible = sessions.filter((s) => {
    if (filter === "archived") {
      if (!s.archived) return false;
    } else if (filter === "orphan") {
      if (!isOrphan(s)) return false;
    } else {
      if (s.archived) return false; // non-archived tabs never show archived rows
      if (filter !== "all" && s.status !== filter) return false;
    }
    if (search) {
      const q = search.toLowerCase();
      return (
        (s.first_name ?? "").toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q) ||
        (s.patient_external_id ?? "").toLowerCase().includes(q) ||
        s.form_id.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center">
            <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
            </svg>
          </div>
          <div>
            <h1 className="text-sm font-bold text-gray-900">Admin Dashboard</h1>
            <p className="text-xs text-gray-400">AI Form Assistant</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/admin/forms"
            className="text-xs font-medium text-indigo-600 hover:text-indigo-800 border border-indigo-200 rounded-lg px-3 py-1.5 hover:bg-indigo-50 transition-colors"
          >
            Form Builder
          </Link>
          <button
            onClick={load}
            disabled={loading}
            className="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <button
            onClick={handleLogout}
            className="text-xs text-red-500 hover:text-red-700 border border-red-200 rounded-lg px-3 py-1.5 hover:bg-red-50 transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: "Applications", value: stats.total, color: "text-gray-900" },
              { label: "In progress", value: stats.active, color: "text-blue-600" },
              { label: "Ready / Completed", value: stats.ready_for_review + stats.completed, color: "text-green-600" },
              { label: "Abandoned (0 answers)", value: stats.orphan, color: "text-gray-500" },
            ].map((s) => (
              <div key={s.label} className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
                <p className="text-xs text-gray-400 uppercase tracking-wider font-medium mb-1">{s.label}</p>
                <p className={`text-3xl font-bold ${s.color}`}>{s.value}</p>
              </div>
            ))}
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-xl p-1 flex-wrap">
            {(["all", "active", "ready_for_review", "completed", "orphan", "archived"] as const).map((f) => {
              const count = f === "orphan" ? stats?.orphan : f === "archived" ? stats?.archived : undefined;
              return (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize ${
                    filter === f
                      ? "bg-indigo-600 text-white"
                      : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
                  }`}
                >
                  {f === "ready_for_review" ? "ready" : f}{count ? ` (${count})` : ""}
                </button>
              );
            })}
          </div>
          {(stats?.orphan ?? 0) > 0 && (
            <button
              onClick={archiveOrphans}
              disabled={!!busy}
              className="text-xs font-medium text-amber-700 border border-amber-200 bg-amber-50 rounded-lg px-3 py-1.5 hover:bg-amber-100 transition-colors disabled:opacity-50"
            >
              Archive {stats?.orphan} abandoned
            </button>
          )}
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by session ID, patient ID, or form…"
            className="flex-1 min-w-[240px] border border-gray-200 rounded-xl px-4 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent bg-white"
          />
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {/* Table */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          {loading && !sessions.length ? (
            <div className="p-12 text-center text-sm text-gray-400">Loading sessions…</div>
          ) : visible.length === 0 ? (
            <div className="p-12 text-center text-sm text-gray-400">No sessions found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">First Name</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Form</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Patient ID</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Status</th>
                    <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Answers</th>
                    <th className="text-center text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">PDF</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Created</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Completed</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {visible.map((s) => (
                    <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-5 py-3 text-sm text-gray-800 font-medium">
                        {s.first_name || <span className="text-gray-300 font-normal text-xs">Not entered</span>}
                      </td>
                      <td className="px-4 py-3 text-gray-700">{s.form_id}</td>
                      <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                        {s.patient_external_id ?? <span className="text-gray-300 font-sans">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={s.status} />
                        {s.mock_mode && (
                          <span className="ml-1.5 text-[10px] text-amber-600 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5 font-medium">
                            MOCK
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                        {s.answer_count}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {s.has_pdf ? (
                          <a
                            href={`${API}/api/session/${s.id}/download-pdf`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
                          >
                            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round"
                                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                            </svg>
                            PDF
                          </a>
                        ) : (
                          <span className="text-gray-300 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                        {fmtDate(s.created_at)}
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                        {fmtDate(s.completed_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
                          <a
                            href={`/review/${s.id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-indigo-600 border border-indigo-200 hover:bg-indigo-50 transition-colors"
                          >
                            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.964-7.178z" />
                              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            </svg>
                            Review
                          </a>
                          {s.archived ? (
                            <button onClick={() => unarchive(s.id)} disabled={!!busy}
                              className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-gray-600 border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-50">
                              Unarchive
                            </button>
                          ) : (
                            <button onClick={() => archive(s.id)} disabled={!!busy}
                              className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-gray-500 border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-50">
                              Archive
                            </button>
                          )}
                          <button onClick={() => remove(s.id)} disabled={!!busy}
                            className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-red-600 border border-red-200 hover:bg-red-50 transition-colors disabled:opacity-50">
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="text-xs text-gray-400 text-right">Showing {visible.length} of {sessions.length} sessions</p>
      </main>
    </div>
  );
}
