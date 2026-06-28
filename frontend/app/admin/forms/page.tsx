"use client";

/**
 * Builder — forms list.
 *
 * Lists every form (any status), lets an admin create a new one, toggle
 * publish/unpublish, delete, or jump into the schema editor. Auth is the same
 * localStorage JWT used by the rest of /admin; api.admin.* injects it and bounces
 * to /admin on 401/403.
 */

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { FormSummary } from "@/lib/types";

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    published: "bg-green-100 text-green-700",
    draft: "bg-amber-100 text-amber-700",
    archived: "bg-gray-100 text-gray-500",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles[status] ?? styles.archived}`}>
      {status}
    </span>
  );
}

export default function FormsBuilderPage() {
  const router = useRouter();
  const [forms, setForms] = useState<FormSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newId, setNewId] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);

  // Auth guard — same pattern as the dashboard.
  useEffect(() => {
    if (typeof window !== "undefined" && !localStorage.getItem("admin_token")) {
      router.replace("/admin");
    }
  }, [router]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setForms(await api.admin.listForms());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load forms.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newId.trim() || !newTitle.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const form = await api.admin.createForm({ form_id: newId.trim(), title: newTitle.trim() });
      router.push(`/admin/forms/${form.form_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed.");
    } finally {
      setCreating(false);
    }
  }

  async function togglePublish(f: FormSummary) {
    setError(null);
    try {
      if (f.status === "published") await api.admin.unpublishForm(f.form_id);
      else await api.admin.publishForm(f.form_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed.");
    }
  }

  async function remove(f: FormSummary) {
    if (!confirm(`Delete form "${f.form_id}"? This cannot be undone.`)) return;
    setError(null);
    try {
      await api.admin.deleteForm(f.form_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    }
  }

  return (
    <div className="admin-screen min-h-screen px-4 py-6 sm:px-6 lg:py-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-950">Form Builder</h1>
            <p className="text-sm text-slate-500">Create and manage forms, prompts, knowledgebase, skills, and workflows.</p>
          </div>
          <Link href="/admin/dashboard" className="inline-flex min-h-11 items-center rounded-lg border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-100">
            ← Dashboard
          </Link>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Create new form */}
        <form
          onSubmit={handleCreate}
          className="mb-6 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div className="flex-1 min-w-[8rem]">
            <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
              Form ID
            </label>
            <input
              value={newId}
              onChange={(e) => setNewId(e.target.value)}
              placeholder="MY_FORM"
              className="w-full border border-slate-300 px-3 outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
            />
          </div>
          <div className="flex-[2] min-w-[12rem]">
            <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
              Title
            </label>
            <input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="My New Form"
              className="w-full border border-slate-300 px-3 outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
            />
          </div>
          <button
            type="submit"
            disabled={creating || !newId.trim() || !newTitle.trim()}
            className="rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {creating ? "Creating…" : "+ New Form"}
          </button>
        </form>

        {/* Forms table */}
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          {loading ? (
            <div className="p-8 text-center text-sm text-gray-400">Loading…</div>
          ) : forms.length === 0 ? (
            <div className="p-8 text-center text-sm text-gray-400">No forms yet. Create one above.</div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                <tr>
                  <th className="text-left px-4 py-2.5 font-semibold">Form</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Status</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Targets</th>
                  <th className="text-right px-4 py-2.5 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {forms.map((f) => (
                  <tr key={f.form_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link href={`/admin/forms/${f.form_id}`} className="font-medium text-gray-800 hover:text-indigo-600">
                        {f.title}
                      </Link>
                      <div className="text-xs text-gray-400">{f.form_id} · v{f.version}</div>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={f.status} /></td>
                    <td className="px-4 py-3 text-xs text-gray-500">{f.output_targets.join(", ")}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <Link
                          href={`/admin/forms/${f.form_id}`}
                          className="inline-flex min-h-10 items-center rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-600 hover:bg-slate-100"
                        >
                          Edit
                        </Link>
                        <button
                          onClick={() => togglePublish(f)}
                          className="rounded-lg border border-slate-300 px-3 text-xs font-semibold text-slate-700 hover:bg-slate-100"
                        >
                          {f.status === "published" ? "Unpublish" : "Publish"}
                        </button>
                        <button
                          onClick={() => remove(f)}
                          className="rounded-lg border border-red-200 px-3 text-xs font-semibold text-red-600 hover:bg-red-50"
                        >
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
      </div>
    </div>
  );
}
