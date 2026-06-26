"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { ReviewResponse, ReviewField, GeneratePdfResponse } from "@/lib/types";

const SOURCE_LABELS: Record<string, { label: string; color: string; dot: string }> = {
  emr:     { label: "EMR",      color: "bg-emerald-100 text-emerald-700",   dot: "bg-emerald-500" },
  user:    { label: "User",     color: "bg-ai-100 text-ai-700",             dot: "bg-ai-500" },
  voice:   { label: "AI Voice", color: "bg-violet-100 text-violet-700",     dot: "bg-violet-500" },
  skipped: { label: "Skipped",  color: "bg-slate-100 text-slate-500",       dot: "bg-slate-400" },
  missing: { label: "Missing",  color: "bg-red-100 text-red-600",           dot: "bg-red-500" },
};

/* ─── Edit Modal ─────────────────────────────────────────────────────── */
interface EditModalProps {
  field: ReviewField;
  sessionId: string;
  onSave: () => void;
  onClose: () => void;
}

function EditModal({ field, sessionId, onSave, onClose }: EditModalProps) {
  const currentValue =
    field.value !== null && field.value !== undefined && field.source !== "skipped"
      ? String(field.value)
      : "";

  const [value, setValue] = useState(currentValue);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detect field type from current value / field key heuristics
  const isDate = /date|dob|birth/i.test(field.field_key);
  const isBool = typeof field.value === "boolean" ||
    (currentValue === "true" || currentValue === "false");

  async function handleSave() {
    const trimmed = value.trim();
    if (!trimmed) { setError("Please enter a value."); return; }
    setSaving(true);
    setError(null);
    try {
      await api.submitAnswer(sessionId, {
        field_key: field.field_key,
        raw_answer: trimmed,
        input_mode: "user",
        confirmed: false,
      });
      onSave();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  // Close on backdrop click
  function handleBackdrop(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose();
  }

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)", backdropFilter: "blur(4px)" }}
      onClick={handleBackdrop}
    >
      <div
        className="w-full max-w-md rounded-2xl shadow-2xl overflow-hidden"
        style={{ background: "#fff" }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <p className="text-[11px] text-gray-400 uppercase tracking-widest mb-0.5">Editing field</p>
            <h3 className="text-base font-semibold text-gray-900">{field.label}</h3>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
          >
            <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-5 space-y-4">
          {/* Current value chip */}
          {currentValue && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">Current:</span>
              <span className="text-xs font-medium text-gray-600 bg-gray-100 px-2.5 py-1 rounded-full">
                {field.is_sensitive ? "•••••" : currentValue}
              </span>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 rounded-xl px-4 py-2.5 text-sm">
              {error}
            </div>
          )}

          {/* Input */}
          {isBool ? (
            <div className="flex gap-3">
              {["yes", "no"].map(opt => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => setValue(opt)}
                  className={`flex-1 py-3 rounded-xl text-sm font-semibold border-2 transition-all capitalize ${
                    value.toLowerCase() === opt
                      ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                      : "border-gray-200 text-gray-500 hover:border-gray-300"
                  }`}
                >
                  {opt === "yes" ? "Yes" : "No"}
                </button>
              ))}
            </div>
          ) : (
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1.5">New answer</label>
              <input
                autoFocus
                type={field.is_sensitive ? "password" : isDate ? "date" : "text"}
                value={value}
                onChange={e => setValue(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !isBool) handleSave(); }}
                placeholder={`Enter ${field.label.toLowerCase()}…`}
                className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent transition-shadow"
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-3 px-5 py-4 border-t border-gray-100 bg-gray-50">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-xl border border-gray-200 text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || (!isBool && !value.trim())}
            className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            style={{ background: "linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%)" }}
          >
            {saving ? (
              <>
                <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                Saving…
              </>
            ) : (
              <>
                <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
                Save answer
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Main review page ───────────────────────────────────────────────── */
export default function ReviewPage() {
  const router = useRouter();
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [review, setReview]         = useState<ReviewResponse | null>(null);
  const [loading, setLoading]       = useState(true);
  const [generating, setGenerating] = useState(false);
  const [pdfResult, setPdfResult]   = useState<GeneratePdfResponse | null>(null);
  const [error, setError]           = useState<string | null>(null);
  const [editField, setEditField]   = useState<ReviewField | null>(null);

  const loadReview = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.getReview(sessionId);
      setReview(r);
    } catch {
      setError("Failed to load review.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => { loadReview(); }, [loadReview]);

  async function handleGeneratePdf() {
    setGenerating(true);
    setError(null);
    try {
      const result = await api.generatePdf(sessionId);
      setPdfResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "PDF generation failed.");
    } finally {
      setGenerating(false);
    }
  }

  function handleEditSaved() {
    setEditField(null);
    loadReview(); // reload to reflect updated value
  }

  /* ─── Loading ── */
  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="flex flex-col items-center gap-3 text-gray-400">
          <div className="h-8 w-8 rounded-full border-2 border-ai-400 border-t-transparent animate-spin" />
          <span className="text-sm">Loading review…</span>
        </div>
      </div>
    );
  }

  if (!review) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-red-600 mb-3">{error || "Review not found."}</p>
          <button onClick={() => router.push("/")} className="text-ai-600 underline text-sm">
            Start over
          </button>
        </div>
      </div>
    );
  }

  const sections = Object.entries(review.sections);

  const totalFilled  = sections.reduce((acc, [, fields]) => acc + fields.filter((f) => f.source !== "skipped" && f.value !== null && f.value !== undefined).length, 0);
  const totalSkipped = sections.reduce((acc, [, fields]) => acc + fields.filter((f) => f.source === "skipped").length, 0);
  const totalFields  = sections.reduce((acc, [, fields]) => acc + fields.length, 0);
  const totalMissing = totalFields - totalFilled - totalSkipped;
  const sourceCounts = sections.reduce<Record<string, number>>((acc, [, fields]) => {
    fields.forEach((f) => {
      if (f.value !== null && f.value !== undefined) {
        acc[f.source] = (acc[f.source] || 0) + 1;
      }
    });
    return acc;
  }, {});

  return (
    <>
      {/* Edit modal */}
      {editField && (
        <EditModal
          field={editField}
          sessionId={sessionId}
          onSave={handleEditSaved}
          onClose={() => setEditField(null)}
        />
      )}

      <div className="max-w-2xl mx-auto px-4 py-8 space-y-5">

        {/* ── Dark summary header ── */}
        <div
          className="rounded-2xl p-6 text-white animate-fade-slide-up"
          style={{ background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)" }}
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="relative h-10 w-10 shrink-0">
              <div className="absolute inset-0 rounded-full ai-orb" />
              <div className="relative z-10 h-full w-full flex items-center justify-center">
                <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
              </div>
            </div>
            <div>
              <h2 className="text-lg font-bold">Review Your Application</h2>
              <p className="text-xs text-slate-400">ODM 07216 – Ohio Medicaid Application</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="bg-white/5 rounded-xl px-4 py-3 text-center border border-white/10">
              <p className="text-2xl font-bold text-white">{totalFilled}</p>
              <p className="text-[10px] text-slate-400 mt-0.5">Fields filled</p>
            </div>
            <div className="bg-white/5 rounded-xl px-4 py-3 text-center border border-white/10">
              <p className="text-2xl font-bold text-emerald-400">{sourceCounts.emr || 0}</p>
              <p className="text-[10px] text-slate-400 mt-0.5">From EMR</p>
            </div>
            <div className="bg-white/5 rounded-xl px-4 py-3 text-center border border-white/10">
              <p className={`text-2xl font-bold ${totalMissing > 0 ? "text-red-400" : "text-emerald-400"}`}>
                {totalMissing}
              </p>
              <p className="text-[10px] text-slate-400 mt-0.5">Missing fields</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 mt-4">
            {Object.entries(SOURCE_LABELS).map(([k, v]) => (
              <div key={k} className="flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${v.dot}`} />
                <span className="text-[10px] text-slate-400">{v.label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Missing fields warning ── */}
        {totalMissing > 0 && (
          <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-5 py-4 text-sm animate-float-in">
            <p className="font-semibold mb-1">
              {totalMissing} field{totalMissing > 1 ? "s" : ""} still missing
              {review.missing_required.length > 0 && (
                <span className="ml-1 text-red-600">({review.missing_required.length} required)</span>
              )}
            </p>
            <p className="text-xs text-amber-700 mb-2">
              {review.missing_required.slice(0, 5).join(", ")}
              {review.missing_required.length > 5 && ` and ${review.missing_required.length - 5} more…`}
            </p>
            <button
              onClick={() => router.push(`/assistant/${sessionId}`)}
              className="text-xs text-amber-800 underline font-medium"
            >
              Go back to complete them
            </button>
          </div>
        )}

        {/* ── All complete banner ── */}
        {totalMissing === 0 && (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl px-5 py-3 text-sm flex items-center gap-2 animate-float-in">
            <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
            All fields are complete.
          </div>
        )}

        {/* ── Field sections ── */}
        {sections.map(([sectionKey, fields]) => {
          if (fields.length === 0) return null;
          const filled = fields.filter((f) => f.source !== "skipped" && f.value !== null && f.value !== undefined);

          return (
            <div key={sectionKey} className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden animate-float-in">
              <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-700">
                  {fields[0]?.section_title || sectionKey.replace(/_/g, " ")}
                </h3>
                <span className="text-xs text-gray-400">{filled.length} / {fields.length} filled</span>
              </div>

              <div className="divide-y divide-gray-50">
                {fields.map((field: ReviewField) => {
                  const isSkipped = field.source === "skipped";
                  const isMissing = !isSkipped && (field.value === null || field.value === undefined);
                  const src = SOURCE_LABELS[field.source] || SOURCE_LABELS.missing;

                  return (
                    <div
                      key={field.field_key}
                      className={`flex items-start px-5 py-3 gap-3 group ${
                        isSkipped ? "bg-slate-50"
                        : isMissing && field.is_required ? "bg-red-50"
                        : isMissing ? "bg-amber-50/60"
                        : ""
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] text-gray-400 uppercase tracking-wide mb-0.5">
                          {field.label}
                          {!field.is_required && (
                            <span className="ml-1.5 text-[9px] text-gray-300 normal-case tracking-normal">(optional)</span>
                          )}
                        </p>
                        <p className={`text-sm font-medium ${
                          isSkipped ? "text-slate-400 italic"
                          : isMissing && field.is_required ? "text-red-400 italic"
                          : isMissing ? "text-amber-400 italic"
                          : "text-gray-800"
                        }`}>
                          {isSkipped ? "Skipped"
                           : isMissing ? "Not provided"
                           : field.is_sensitive ? "•••••••"
                           : String(field.value)}
                        </p>
                      </div>

                      {/* Source badge + edit button */}
                      <div className="shrink-0 flex items-center gap-2 mt-0.5">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${src.color}`}>
                          {src.label}
                        </span>
                        {!field.is_sensitive && (
                          <button
                            onClick={() => setEditField(field)}
                            title="Edit this answer"
                            className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition-all"
                          >
                            <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round"
                                d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zM19.5 7.125L16.875 4.5" />
                            </svg>
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}

        {/* ── PDF generation card ── */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 space-y-3 animate-float-in">
          <h3 className="text-base font-semibold text-gray-800 mb-1">Generate Your PDF</h3>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-2.5 text-sm">
              {error}
            </div>
          )}

          {pdfResult ? (
            <div className="space-y-3">
              <div className={`rounded-xl px-4 py-3 text-sm flex items-start gap-2 ${
                pdfResult.is_fallback
                  ? "bg-amber-50 border border-amber-200 text-amber-800"
                  : "bg-emerald-50 border border-emerald-200 text-emerald-700"
              }`}>
                {pdfResult.is_fallback ? (
                  <>
                    <svg className="h-4 w-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                    </svg>
                    <span>
                      PDF generated as summary (fallback mode — base PDF not found).
                      Place <code className="text-xs bg-amber-100 px-1 rounded">ODM07216fillx.pdf</code> in{" "}
                      <code className="text-xs bg-amber-100 px-1 rounded">backend/app/pdf/</code> for field-filled output.
                    </span>
                  </>
                ) : (
                  <>
                    <svg className="h-4 w-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                    PDF generated successfully with all filled form fields.
                  </>
                )}
              </div>

              <a
                href={api.downloadPdfUrl(sessionId)}
                download={pdfResult.file_name}
                className="flex items-center justify-center gap-2 w-full rounded-xl py-3 text-sm font-semibold text-white transition-all hover:opacity-90"
                style={{ background: "linear-gradient(135deg, #059669 0%, #10b981 100%)" }}
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                </svg>
                Download — {pdfResult.file_name}
              </a>

              <button
                onClick={handleGeneratePdf}
                className="w-full border border-gray-200 text-gray-500 rounded-xl py-2.5 text-sm hover:bg-gray-50 transition-colors"
              >
                Re-generate PDF
              </button>
            </div>
          ) : (
            <button
              onClick={handleGeneratePdf}
              disabled={generating}
              className="w-full rounded-xl py-3 text-sm font-semibold text-white transition-all disabled:opacity-60 flex items-center justify-center gap-2"
              style={{ background: "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)" }}
            >
              {generating ? (
                <>
                  <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Generating PDF…
                </>
              ) : (
                <>
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round"
                      d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                  </svg>
                  Generate PDF
                </>
              )}
            </button>
          )}

          <button
            onClick={() => router.push(`/assistant/${sessionId}`)}
            className="w-full border border-gray-200 text-gray-600 rounded-xl py-2.5 text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            Back to form
          </button>
        </div>

        <p className="text-xs text-center text-gray-400 pb-6">
          This assistant helps complete the form but does not determine eligibility or provide
          legal advice. Please review all answers before submitting or using the generated PDF.
        </p>
      </div>
    </>
  );
}
