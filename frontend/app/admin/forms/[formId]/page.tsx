"use client";

/**
 * Builder - form editor.
 *
 * Edit a form's metadata (title / version / output targets) and its field schema.
 * The schema editor is structured (sections -> fields with the common props) with a
 * raw-JSON escape hatch for advanced edits (validation_rule, depends_on, prefill, ...).
 * Saving the schema calls PUT /api/admin/forms/{id}/schema; if the form is published
 * the change is live in the patient flow immediately (server-side cache sync).
 */

import { useState, useEffect, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { FormDetail, FormSchemaDoc, SectionDef, FieldDef, KbDocSummary, SkillCatalogItem } from "@/lib/types";

const FIELD_TYPES = ["text", "textarea", "date", "boolean", "phone", "ssn", "number", "select", "email"];
const OUTPUT_TARGETS = ["pdf", "web"];
const WORKFLOW_TASK_TYPES = ["generate_pdf", "web_submit"];

type WorkflowEditorTask = { type: string; configText: string };

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

  // Prompt pack + voice: per-form AI persona, per-field question overrides, voice config.
  const [persona, setPersona] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [sttVocab, setSttVocab] = useState("");
  const [overrides, setOverrides] = useState<Record<string, string>>({});

  // Knowledgebase docs (PHI-free guidance for RAG help).
  const [kbDocs, setKbDocs] = useState<KbDocSummary[]>([]);
  const [kbTitle, setKbTitle] = useState("");
  const [kbText, setKbText] = useState("");

  // Skills (reusable AI capabilities) - catalog + which are attached to this form.
  const [skillCatalog, setSkillCatalog] = useState<SkillCatalogItem[]>([]);
  const [attachedSkills, setAttachedSkills] = useState<string[]>([]);

  // Completion workflow (ordered tasks that run after the user approves).
  const [wfTasks, setWfTasks] = useState<WorkflowEditorTask[]>([]);

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
      // Hydrate prompt pack + voice from the form record.
      const prompt = (f.prompt ?? {}) as { system?: string; field_overrides?: Record<string, { question?: string }> };
      setPersona(prompt.system ?? "");
      const ov: Record<string, string> = {};
      Object.entries(prompt.field_overrides ?? {}).forEach(([k, v]) => {
        if (v?.question) ov[k] = v.question;
      });
      setOverrides(ov);
      const voice = (f.voice ?? {}) as { voice_id?: string; stt_vocabulary?: string };
      setVoiceId(voice.voice_id ?? "");
      setSttVocab(voice.stt_vocabulary ?? "");
      setWfTasks(
        ((f.workflow?.tasks as { type: string; config?: Record<string, unknown> }[] | undefined) ?? [{ type: "generate_pdf" }])
          .map((task) => ({
            type: task.type,
            configText: JSON.stringify(task.config ?? {}, null, 2),
          }))
      );
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

  const loadKb = useCallback(async () => {
    try {
      setKbDocs(await api.admin.listKb(formId));
    } catch {
      /* KB is optional; ignore load errors */
    }
  }, [formId]);

  useEffect(() => {
    loadKb();
  }, [loadKb]);

  useEffect(() => {
    api.admin.listSkillCatalog().then(setSkillCatalog).catch(() => {});
    api.admin.getFormSkills(formId).then((r) => setAttachedSkills(r.attached)).catch(() => {});
  }, [formId]);

  async function toggleSkill(key: string) {
    const next = attachedSkills.includes(key)
      ? attachedSkills.filter((k) => k !== key)
      : [...attachedSkills, key];
    setAttachedSkills(next);
    try {
      await api.admin.setFormSkills(formId, next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    }
  }

  async function saveWorkflow() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const tasks = wfTasks.map((task, index) => {
        let config: Record<string, unknown> = {};
        try {
          config = task.configText.trim() ? JSON.parse(task.configText) : {};
        } catch {
          throw new Error(`Step ${index + 1} config is not valid JSON.`);
        }
        return Object.keys(config).length > 0 ? { type: task.type, config } : { type: task.type };
      });
      await api.admin.updateFormWorkflow(formId, { tasks, approval: { required: true } });
      setNotice("Workflow saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function addKb() {
    if (!kbTitle.trim() || !kbText.trim()) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await api.admin.createKb(formId, { title: kbTitle.trim(), text: kbText.trim() });
      setKbTitle("");
      setKbText("");
      await loadKb();
      setNotice("Knowledgebase document added & embedded.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Add failed.");
    } finally {
      setSaving(false);
    }
  }

  async function delKb(docId: number) {
    setError(null);
    try {
      await api.admin.deleteKb(formId, docId);
      await loadKb();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    }
  }

  // -- immutable schema mutations (keep rawText mirrored) --
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
      setSchema(f.schema);
      setRawText(JSON.stringify(f.schema, null, 2));
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

  async function savePrompts() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const field_overrides: Record<string, { question: string }> = {};
      Object.entries(overrides).forEach(([k, q]) => {
        if (q.trim()) field_overrides[k] = { question: q.trim() };
      });
      const f = await api.admin.updateFormPrompts(formId, {
        prompt: { system: persona, field_overrides },
        voice: { voice_id: voiceId || null, stt_vocabulary: sttVocab || null },
      });
      setForm(f);
      setNotice("Prompts & voice saved." + (f.status === "published" ? " Live now." : ""));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
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
      setNotice(f.status === "published" ? "Published - now in the patient picker." : "Unpublished - hidden from patients.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed.");
    }
  }

  if (loading) return <div className="admin-screen min-h-screen p-8 text-sm text-slate-500">Loading...</div>;
  if (!form || !schema) return <div className="admin-screen min-h-screen p-8 text-sm text-red-600">{error ?? "Not found."}</div>;

  const isPublished = form.status === "published";

  return (
    <div className="admin-screen min-h-screen px-4 py-6 sm:px-6 lg:py-8">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-6 flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
          <div>
            <Link href="/admin/forms" className="inline-flex min-h-10 items-center text-sm font-semibold text-slate-600 hover:text-slate-950">
              Back to forms
            </Link>
            <h1 className="mt-1 text-2xl font-semibold text-slate-950">{form.title}</h1>
            <p className="text-xs text-slate-500">
              {form.form_id} |{" "}
              <span className={isPublished ? "text-green-600" : "text-amber-600"}>{form.status}</span>
            </p>
          </div>
          <button
            onClick={togglePublish}
            className={`rounded-lg px-4 text-sm font-semibold text-white ${
              isPublished ? "bg-amber-500 hover:bg-amber-400" : "bg-green-600 hover:bg-green-500"
            }`}
          >
            {isPublished ? "Unpublish" : "Publish"}
          </button>
        </div>

        {error && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        {notice && <div className="mb-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">{notice}</div>}

        {/* Metadata */}
        <section className="mb-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-700">Details</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="sm:col-span-2 block">
              <span className="block text-xs font-semibold text-gray-500 mb-1">Title</span>
              <input value={title} onChange={(e) => setTitle(e.target.value)}
                className="w-full border border-slate-300 px-3 outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
            </label>
            <label className="block">
              <span className="block text-xs font-semibold text-gray-500 mb-1">Version</span>
              <input value={version} onChange={(e) => setVersion(e.target.value)}
                className="w-full border border-slate-300 px-3 outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
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
                  {t === "web" && <span className="text-xs text-gray-400">(web submission)</span>}
                </label>
              ))}
            </div>
          </div>
          <button onClick={saveMeta} disabled={saving}
            className="mt-4 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
            {saving ? "Saving..." : "Save details"}
          </button>
        </section>

        {/* Schema editor */}
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
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
              className="h-[28rem] w-full rounded-lg border border-slate-300 p-3 font-mono text-xs outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
            />
          ) : (
            <div className="space-y-5">
              {schema.sections.map((sec, si) => (
                <div key={si} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
                    <input
                      value={sec.section_title}
                      onChange={(e) => patchSection(si, { section_title: e.target.value })}
                      className="flex-1 border border-slate-300 bg-white px-3 font-semibold outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
                    />
                    <button onClick={() => removeSection(si)} className="rounded-lg border border-red-200 px-3 text-xs font-semibold text-red-600 hover:bg-red-50">remove section</button>
                  </div>

                  <div className="space-y-2">
                    {sec.fields.map((fld, fi) => (
                      <div key={fi} className="rounded-lg border border-slate-200 bg-white p-3">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          <label className="block">
                            <span className="block text-[10px] font-semibold text-gray-400 uppercase">Field key</span>
                            <input value={fld.field_key} onChange={(e) => patchField(si, fi, { field_key: e.target.value })}
                              className="w-full border border-slate-300 px-2 font-mono text-xs outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
                          </label>
                          <label className="block">
                            <span className="block text-[10px] font-semibold text-gray-400 uppercase">Label</span>
                            <input value={fld.label} onChange={(e) => patchField(si, fi, { label: e.target.value })}
                              className="w-full border border-slate-300 px-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
                          </label>
                        </div>
                        <label className="block mt-2">
                          <span className="block text-[10px] font-semibold text-gray-400 uppercase">Question text</span>
                          <input value={fld.question_text ?? ""} onChange={(e) => patchField(si, fi, { question_text: e.target.value })}
                            placeholder="What is...?"
                            className="w-full border border-slate-300 px-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
                        </label>
                        <div className="flex flex-wrap items-center gap-3 mt-2">
                          <label className="flex items-center gap-1 text-xs text-gray-600">
                            type
                            <select value={fld.type} onChange={(e) => patchField(si, fi, { type: e.target.value })}
                              className="rounded-lg border border-slate-300 px-2 text-sm">
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
                          <button onClick={() => removeField(si, fi)} className="ml-auto rounded-lg border border-red-200 px-3 text-xs font-semibold text-red-600 hover:bg-red-50">remove</button>
                        </div>
                      </div>
                    ))}
                  </div>
                  <button onClick={() => addField(si)} className="mt-3 rounded-lg border border-slate-300 px-3 text-xs font-semibold text-slate-700 hover:bg-white">
                    + Add field
                  </button>
                </div>
              ))}
              <button onClick={addSection} className="rounded-lg border border-slate-300 px-4 text-xs font-semibold text-slate-700 hover:bg-slate-100">
                + Add section
              </button>
            </div>
          )}

          <div className="mt-5 flex items-center gap-3">
            <button onClick={saveSchema} disabled={saving}
              className="rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
              {saving ? "Saving..." : "Save schema"}
            </button>
            <span className="text-xs text-gray-400">
              {isPublished ? "Published - saves go live immediately." : "Draft - publish to use in the patient flow."}
            </span>
          </div>
        </section>

        {/* Prompts & voice */}
        <section className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-700">Prompts &amp; Voice</h2>

          <label className="block mb-4">
            <span className="block text-xs font-semibold text-gray-500 mb-1">AI persona (system prompt)</span>
            <textarea
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              rows={4}
              placeholder="You are a warm, patient assistant helping complete this form..."
              className="w-full rounded-lg border border-slate-300 p-3 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
            />
            <span className="text-xs text-gray-400">Sets the assistant&apos;s tone. Structural voice/format rules are always kept.</span>
          </label>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <label className="block">
              <span className="block text-xs font-semibold text-gray-500 mb-1">Voice ID (ElevenLabs)</span>
              <input value={voiceId} onChange={(e) => setVoiceId(e.target.value)} placeholder="(global default)"
                className="w-full border border-slate-300 px-3 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
            </label>
            <label className="block">
              <span className="block text-xs font-semibold text-gray-500 mb-1">Speech vocabulary hints</span>
              <input value={sttVocab} onChange={(e) => setSttVocab(e.target.value)} placeholder="Medicaid, applicant, household..."
                className="w-full border border-slate-300 px-3 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
            </label>
          </div>

          <div>
            <span className="block text-xs font-semibold text-gray-500 mb-2">
              Per-field question overrides <span className="text-gray-400 normal-case font-normal">(optional - reword how a field is asked)</span>
            </span>
            <div className="space-y-1.5 max-h-72 overflow-auto pr-1">
              {schema.sections.flatMap((sec) => sec.fields).map((fld) => (
                <div key={fld.field_key} className="flex items-center gap-2">
                  <span className="text-xs font-mono text-gray-400 w-40 shrink-0 truncate" title={fld.field_key}>
                    {fld.field_key}
                  </span>
                  <input
                    value={overrides[fld.field_key] ?? ""}
                    onChange={(e) => setOverrides((p) => ({ ...p, [fld.field_key]: e.target.value }))}
                    placeholder={fld.question_text ?? fld.label}
                    className="min-w-0 flex-1 border border-slate-300 px-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
                  />
                </div>
              ))}
            </div>
          </div>

          <button onClick={savePrompts} disabled={saving}
            className="mt-4 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
            {saving ? "Saving..." : "Save prompts & voice"}
          </button>
        </section>

        {/* Knowledgebase */}
        <section className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-700">Knowledgebase</h2>
          <p className="text-xs text-gray-400 mb-3">
            PHI-free guidance the assistant retrieves to help users (e.g. &quot;what counts as income?&quot;). No patient data.
          </p>

          <div className="space-y-1.5 mb-4">
            {kbDocs.length === 0 ? (
              <p className="text-xs text-gray-400">No documents yet.</p>
            ) : (
              kbDocs.map((d) => (
                <div key={d.id} className="flex flex-col gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm sm:flex-row sm:items-center">
                  <span className="flex-1 truncate">{d.title}</span>
                  <span className="text-xs text-gray-400">{d.chunk_count} chunks | {d.status}</span>
                  <button onClick={() => delKb(d.id)} className="rounded-lg border border-red-200 px-3 text-xs font-semibold text-red-600 hover:bg-red-50">delete</button>
                </div>
              ))
            )}
          </div>

          <div className="space-y-2">
            <input value={kbTitle} onChange={(e) => setKbTitle(e.target.value)} placeholder="Document title"
              className="w-full border border-slate-300 px-3 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
            <textarea value={kbText} onChange={(e) => setKbText(e.target.value)} rows={4} placeholder="Paste PHI-free guidance text..."
              className="w-full rounded-lg border border-slate-300 p-3 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200" />
            <button onClick={addKb} disabled={saving || !kbTitle.trim() || !kbText.trim()}
              className="rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
              {saving ? "Adding..." : "+ Add & embed"}
            </button>
          </div>
        </section>

        {/* Skills */}
        <section className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-700">Skills</h2>
          <p className="text-xs text-gray-400 mb-3">Reusable AI capabilities this form&apos;s assistant can use (toggles save instantly).</p>
          <div className="space-y-2">
            {skillCatalog.map((s) => (
              <label key={s.key} className="flex min-h-14 cursor-pointer items-start gap-2.5 rounded-lg border border-slate-200 px-3 py-2 text-sm hover:bg-slate-50">
                <input type="checkbox" checked={attachedSkills.includes(s.key)} onChange={() => toggleSkill(s.key)} className="mt-0.5" />
                <span>
                  <span className="font-medium text-gray-800">{s.name}</span>
                  {s.needs_network && <span className="ml-2 text-[10px] text-amber-600 uppercase tracking-wide">network</span>}
                  <span className="block text-xs text-gray-400">{s.description}</span>
                </span>
              </label>
            ))}
          </div>
        </section>

        {/* Completion workflow */}
        <section className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-700">Completion Workflow</h2>
          <p className="text-xs text-gray-400 mb-3">Ordered steps that run after the user reviews &amp; approves their answers.</p>
          <div className="space-y-2 mb-3">
            {wfTasks.map((t, i) => (
              <div key={i} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-5">{i + 1}.</span>
                  <select
                    value={t.type}
                    onChange={(e) => setWfTasks((p) => p.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}
                    className="flex-1 rounded-lg border border-slate-300 px-2 text-sm"
                  >
                    {WORKFLOW_TASK_TYPES.map((tt) => (
                      <option key={tt} value={tt}>{tt}</option>
                    ))}
                  </select>
                  <button onClick={() => setWfTasks((p) => p.filter((_, j) => j !== i))} className="rounded-lg border border-red-200 px-3 text-xs font-semibold text-red-600 hover:bg-red-50">remove</button>
                </div>
                <textarea
                  value={t.configText}
                  onChange={(e) => setWfTasks((p) => p.map((x, j) => (j === i ? { ...x, configText: e.target.value } : x)))}
                  rows={t.type === "web_submit" ? 6 : 2}
                  spellCheck={false}
                  className="mt-2 w-full rounded-lg border border-slate-300 p-2 font-mono text-xs outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
                  placeholder={t.type === "web_submit" ? '{\n  "recipe": {\n    "portal_url": "https://example.test/apply",\n    "field_selectors": {}\n  }\n}' : "{}"}
                />
              </div>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => setWfTasks((p) => [...p, { type: "generate_pdf", configText: "{}" }])}
              className="rounded-lg border border-slate-300 px-3 text-xs font-semibold text-slate-700 hover:bg-slate-100">
              + Add step
            </button>
            <button onClick={saveWorkflow} disabled={saving}
              className="rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">
              {saving ? "Saving..." : "Save workflow"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
