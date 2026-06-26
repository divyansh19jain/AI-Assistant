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
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Form Builder</h1>
            <p className="text-sm text-gray-500">Create and manage the forms patients can complete.</p>
          </div>
          <Link href="/admin/dashboard" className="text-sm text-indigo-600 hover:underline">
            ← Dashboard
          </Link>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-2.5 text-sm mb-4">
            {error}
          </div>
        )}

        {/* Create new form */}
        <form
          onSubmit={handleCreate}
          className="bg-white border border-gray-200 rounded-2xl p-4 mb-6 flex flex-wrap items-end gap-3"
        >
          <div className="flex-1 min-w-[8rem]">
            <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
              Form ID
            </label>
            <input
              value={newId}
              onChange={(e) => setNewId(e.target.value)}
              placeholder="MY_FORM"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
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
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
          <button
            type="submit"
            disabled={creating || !newId.trim() || !newTitle.trim()}
            className="rounded-lg px-4 py-2 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
          >
            {creating ? "Creating…" : "+ New Form"}
          </button>
        </form>

        {/* Forms table */}
        <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
          {loading ? (
            <div className="p-8 text-center text-sm text-gray-400">Loading…</div>
          ) : forms.length === 0 ? (
            <div className="p-8 text-center text-sm text-gray-400">No forms yet. Create one above.</div>
          ) : (
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
                          className="text-xs px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-100"
                        >
                          Edit
                        </Link>
                        <button
                          onClick={() => togglePublish(f)}
                          className="text-xs px-2.5 py-1 rounded-md border border-indigo-200 text-indigo-600 hover:bg-indigo-50"
                        >
                          {f.status === "published" ? "Unpublish" : "Publish"}
                        </button>
                        <button
                          onClick={() => remove(f)}
                          className="text-xs px-2.5 py-1 rounded-md border border-red-200 text-red-600 hover:bg-red-50"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
