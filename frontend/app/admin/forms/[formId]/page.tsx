"use client";

/**
 * Builder — form editor.
 *
 * Edit a form's metadata (title / version / output targets) and its field schema.
 * The schema editor is structured (sections -> fields with the common props) with a
 * raw-JSON escape hatch for advanced edits (validation_rule, depends_on, prefill, …).
 * Saving the schema calls PUT /api/admin/forms/{id}/schema; if the form is published
 * the change is live in the patient flow immediately (server-side cache sync).
 */

import { useState, useEffect, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { FormDetail, FormSchemaDoc, SectionDef, FieldDef } from "@/lib/types";

const FIELD_TYPES = ["text", "textarea", "date", "boolean", "phone", "ssn", "number", "select"];
const OUTPUT_TARGETS = ["pdf", "web"];

export default function FormEditorPage() {
  const router = useRouter();
  const params = useParams();
  const formId = String(params.formId);

  const [form, setForm] = useState<FormDetail | null>(null);
  const [schema, setSchema] = useState<FormSchemaDoc | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState("");

  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("");
  const [targets, setTargets] = useState<string[]>([]);

  useEffect(() => {
    if (typeof window !== "undefined" && !localStorage.getItem("admin_token")) router.replace("/admin");
  }, [router]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const f = await api.admin.getForm(formId);
      setForm(f);
      setSchema(f.schema);
      setTitle(f.title);
      setVersion(f.version);
      setTargets(f.output_targets);
      setRawText(JSON.stringify(f.schema, null, 2));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed.");
    } finally {
      setLoading(false);
    }
  }, [formId]);

  useEffect(() => {
    load();
  }, [load]);

  // ── immutable schema mutations (keep rawText mirrored) ──
  function commit(next: FormSchemaDoc) {
    setSchema(next);
    setRawText(JSON.stringify(next, null, 2));
  }
  function patchSection(si: number, patch: Partial<SectionDef>) {
    if (!schema) return;
    commit({ ...schema, sections: schema.sections.map((s, i) => (i === si ? { ...s, ...patch } : s)) });
  }
  function patchField(si: number, fi: number, patch: Partial<FieldDef>) {
    if (!schema) return;
    commit({
      ...schema,
      sections: schema.sections.map((s, i) =>
        i === si ? { ...s, fields: s.fields.map((fl, j) => (j === fi ? { ...fl, ...patch } : fl)) } : s
      ),
    });
  }
  function addField(si: number) {
    if (!schema) return;
    const sec = schema.sections[si];
    const field: FieldDef = {
      field_key: `${sec.section_key}.field_${sec.fields.length + 1}`,
      label: "New Field",
      section: sec.section_key,
      type: "text",
      required: false,
      sensitive: false,
      question_text: "",
    };
    commit({ ...schema, sections: schema.sections.map((s, i) => (i === si ? { ...s, fields: [...s.fields, field] } : s)) });
  }
  function removeField(si: number, fi: number) {
    if (!schema) return;
    commit({
      ...schema,
      sections: schema.sections.map((s, i) => (i === si ? { ...s, fields: s.fields.filter((_, j) => j !== fi) } : s)),
    });
  }
  function addSection() {
    if (!schema) return;
    const n = schema.sections.length + 1;
    commit({ ...schema, sections: [...schema.sections, { section_key: `section_${n}`, section_title: `Section ${n}`, fields: [] }] });
  }
  function removeSection(si: number) {
    if (!schema || !confirm("Remove this section and its fields?")) return;
    commit({ ...schema, sections: schema.sections.filter((_, i) => i !== si) });
  }

  async function saveMeta() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const f = await api.admin.updateFormMeta(formId, { title, version, output_targets: targets });
      setForm(f);
      setNotice("Metadata saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function saveSchema() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      let toSave: FormSchemaDoc;
      if (rawMode) {
        toSave = JSON.parse(rawText) as FormSchemaDoc;
        if (!Array.isArray(toSave.sections)) throw new Error("Schema must have a 'sections' array.");
      } else {
        if (!schema) throw new Error("No schema loaded.");
        toSave = schema;
      }
      const f = await api.admin.updateFormSchema(formId, toSave);
      setForm(f);
      setSchema(f.schema);
      setRawText(JSON.stringify(f.schema, null, 2));
      setNotice("Schema saved." + (f.status === "published" ? " Live in the patient flow." : ""));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed (invalid JSON?).");
    } finally {
      setSaving(false);
    }
  }

  async function togglePublish() {
    if (!form) return;
    setError(null);
    try {
      const f = form.status === "published" ? await api.admin.unpublishForm(formId) : await api.admin.publishForm(formId);
      setForm(f);
      setNotice(f.status === "published" ? "Published — now in the patient picker." : "Unpublished — hidden from patients.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed.");
    }
  }

  if (loading) return <div className="min-h-screen bg-gray-50 p-8 text-sm text-gray-400">Loading…</div>;
  if (!form || !schema) return <div className="min-h-screen bg-gray-50 p-8 text-sm text-red-600">{error ?? "Not found."}</div>;

  const isPublished = form.status === "published";

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <Link href="/admin/forms" className="text-sm text-indigo-600 hover:underline">
              ← All forms
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 mt-1">{form.title}</h1>
            <p className="text-xs text-gray-400">
              {form.form_id} ·{" "}
              <span className={isPublished ? "text-green-600" : "text-amber-600"}>{form.status}</span>
            </p>
          </div>
          <button
            onClick={togglePublish}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white ${
              isPublished ? "bg-amber-500 hover:bg-amber-400" : "bg-green-600 hover:bg-green-500"
            }`}
          >
            {isPublished ? "Unpublish" : "Publish"}
          </button>
        </div>

        {error && <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-2.5 text-sm mb-4">{error}</div>}
        {notice && <div className="bg-green-50 border border-green-200 text-green-700 rounded-xl px-4 py-2.5 text-sm mb-4">{notice}</div>}

        {/* Metadata */}
        <section className="bg-white border border-gray-200 rounded-2xl p-5 mb-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">Details</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="sm:col-span-2 block">
              <span className="block text-xs font-semibold text-gray-500 mb-1">Title</span>
              <input value={title} onChange={(e) => setTitle(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
            </label>
            <label className="block">
              <span className="block text-xs font-semibold text-gray-500 mb-1">Version</span>
              <input value={version} onChange={(e) => setVersion(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
            </label>
          </div>
          <div className="mt-3">
            <span className="block text-xs font-semibold text-gray-500 mb-1">Completion targets</span>
            <div className="flex gap-4">
              {OUTPUT_TARGETS.map((t) => (
                <label key={t} className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={targets.includes(t)}
                    onChange={() => setTargets((p) => (p.includes(t) ? p.filter((x) => x !== t) : [...p, t]))}
                  />
                  {t.toUpperCase()}
                  {t === "web" && <span className="text-xs text-gray-400">(submission — Phase G)</span>}
                </label>
              ))}
            </div>
          </div>
          <button onClick={saveMeta} disabled={saving}
            className="mt-4 rounded-lg px-4 py-2 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50">
            {saving ? "Saving…" : "Save details"}
          </button>
        </section>

        {/* Schema editor */}
        <section className="bg-white border border-gray-200 rounded-2xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Fields</h2>
            <label className="flex items-center gap-2 text-xs text-gray-500">
              <input type="checkbox" checked={rawMode} onChange={(e) => setRawMode(e.target.checked)} />
              Raw JSON
            </label>
          </div>

          {rawMode ? (
            <textarea
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
              spellCheck={false}
              className="w-full h-[28rem] font-mono text-xs border border-gray-200 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          ) : (
            <div className="space-y-5">
              {schema.sections.map((sec, si) => (
                <div key={si} className="border border-gray-150 rounded-xl p-4 bg-gray-50/50">
                  <div className="flex items-center gap-2 mb-3">
                    <input
                      value={sec.section_title}
                      onChange={(e) => patchSection(si, { section_title: e.target.value })}
                      className="flex-1 font-semibold text-sm bg-transparent border-b border-gray-200 focus:outline-none focus:border-indigo-400 py-1"
                    />
                    <button onClick={() => removeSection(si)} className="text-xs text-red-500 hover:underline">remove section</button>
                  </div>

                  <div className="space-y-2">
                    {sec.fields.map((fld, fi) => (
                      <div key={fi} className="bg-white border border-gray-200 rounded-lg p-3">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          <label className="block">
                            <span className="block text-[10px] font-semibold text-gray-400 uppercase">Field key</span>
                            <input value={fld.field_key} onChange={(e) => patchField(si, fi, { field_key: e.target.value })}
                              className="w-full font-mono text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-400" />
                          </label>
                          <label className="block">
                            <span className="block text-[10px] font-semibold text-gray-400 uppercase">Label</span>
                            <input value={fld.label} onChange={(e) => patchField(si, fi, { label: e.target.value })}
                              className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-400" />
                          </label>
                        </div>
                        <label className="block mt-2">
                          <span className="block text-[10px] font-semibold text-gray-400 uppercase">Question text</span>
                          <input value={fld.question_text ?? ""} onChange={(e) => patchField(si, fi, { question_text: e.target.value })}
                            placeholder="What is…?"
                            className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-400" />
                        </label>
                        <div className="flex flex-wrap items-center gap-3 mt-2">
                          <label className="flex items-center gap-1 text-xs text-gray-600">
                            type
                            <select value={fld.type} onChange={(e) => patchField(si, fi, { type: e.target.value })}
                              className="text-xs border border-gray-200 rounded px-1.5 py-1">
                              {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                            </select>
                          </label>
                          <label className="flex items-center gap-1.5 text-xs text-gray-600">
                            <input type="checkbox" checked={!!fld.required} onChange={(e) => patchField(si, fi, { required: e.target.checked })} />
                            required
                          </label>
                          <label className="flex items-center gap-1.5 text-xs text-gray-600">
                            <input type="checkbox" checked={!!fld.sensitive} onChange={(e) => patchField(si, fi, { sensitive: e.target.checked })} />
                            sensitive (PHI)
                          </label>
                          <button onClick={() => removeField(si, fi)} className="ml-auto text-xs text-red-500 hover:underline">remove</button>
                        </div>
                      </div>
                    ))}
                  </div>
                  <button onClick={() => addField(si)} className="mt-3 text-xs px-2.5 py-1 rounded-md border border-indigo-200 text-indigo-600 hover:bg-indigo-50">
                    + Add field
                  </button>
                </div>
              ))}
              <button onClick={addSection} className="text-xs px-3 py-1.5 rounded-md border border-gray-300 text-gray-600 hover:bg-gray-100">
                + Add section
              </button>
            </div>
          )}

          <div className="mt-5 flex items-center gap-3">
            <button onClick={saveSchema} disabled={saving}
              className="rounded-lg px-4 py-2 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50">
              {saving ? "Saving…" : "Save schema"}
            </button>
            <span className="text-xs text-gray-400">
              {isPublished ? "Published — saves go live immediately." : "Draft — publish to use in the patient flow."}
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}
