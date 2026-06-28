"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { CLINICAL_BATTERY_FORM_ID, selectedToolGateAnswers } from "@/lib/clinical";
import type { MaskedPatient, PatientSearchResponse } from "@/lib/types";

export default function PatientMatchPage() {
  const router = useRouter();
  const [result, setResult] = useState<PatientSearchResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stored = sessionStorage.getItem("patientSearchResult");
    if (!stored) {
      router.replace("/");
      return;
    }
    const parsed = JSON.parse(stored) as PatientSearchResponse;
    // Discard stale cached results that used the old masked field names
    if (parsed.matches?.length > 0 && "masked_first_name" in parsed.matches[0]) {
      sessionStorage.removeItem("patientSearchResult");
      router.replace("/");
      return;
    }
    setResult(parsed);
  }, [router]);

  async function handleConfirm() {
    if (!selected) return;
    setLoading(true);
    try {
      // Use the form chosen on the landing page (carried via sessionStorage); fall back
      // to the backend default if absent.
      const formId = (typeof window !== "undefined" && sessionStorage.getItem("selectedFormId")) || undefined;
      const selectedTools = JSON.parse(sessionStorage.getItem("selectedClinicalTools") || "[]") as string[];
      const session = await api.createSession({
        patient_id: selected,
        form_id: formId,
        initial_answers: formId === CLINICAL_BATTERY_FORM_ID ? selectedToolGateAnswers(selectedTools) : undefined,
      });
      router.push(`/assistant/${session.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start session.");
    } finally {
      setLoading(false);
    }
  }

  async function handleManual() {
    setLoading(true);
    try {
      const formId = (typeof window !== "undefined" && sessionStorage.getItem("selectedFormId")) || undefined;
      const selectedTools = JSON.parse(sessionStorage.getItem("selectedClinicalTools") || "[]") as string[];
      const session = await api.createSession({
        manual_mode: true,
        form_id: formId,
        initial_answers: formId === CLINICAL_BATTERY_FORM_ID ? selectedToolGateAnswers(selectedTools) : undefined,
      });
      router.push(`/assistant/${session.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start session.");
    } finally {
      setLoading(false);
    }
  }

  if (!result) {
    return (
      <div className="flex items-center justify-center min-h-screen"
        style={{ background: "linear-gradient(160deg,#f8faff 0%,#eef2ff 50%,#f5f3ff 100%)" }}>
        <div className="flex flex-col items-center gap-3 text-gray-400">
          <div className="h-8 w-8 rounded-full border-2 border-ai-400 border-t-transparent animate-spin" />
          <span className="text-sm">Loading results…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-10"
      style={{ background: "linear-gradient(160deg,#f8faff 0%,#eef2ff 50%,#f5f3ff 100%)" }}>
      <div className="w-full max-w-md animate-fade-slide-up">
        {/* Header */}
        <div className="text-center mb-6">
          <div className="relative mx-auto mb-4 h-16 w-16">
            <div className="absolute inset-0 rounded-full ai-orb" />
            <div className="relative z-10 h-full w-full flex items-center justify-center">
              <svg
                className="h-7 w-7 text-white"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"
                />
              </svg>
            </div>
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-1">
            {result.count === 0 ? "No records found" : "Is this you?"}
          </h2>
          <p className="text-sm text-gray-500">
            {result.count === 0
              ? "We couldn't find matching records in the EMR system."
              : `Found ${result.count} matching record${result.count > 1 ? "s" : ""}. Select yours to continue.`}
          </p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
          {result.is_mock && (
            <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-4 py-2.5 text-xs mb-4 flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
              MOCK MODE — Results are simulated for development.
            </div>
          )}

          {result.message && (
            <div className="bg-ai-50 border border-ai-100 text-ai-700 rounded-xl px-4 py-2.5 text-xs mb-4">
              {result.message}
            </div>
          )}

          {/* Patient cards */}
          {result.matches.length > 0 && (
            <div className="space-y-3 mb-5">
              {result.matches.map((match: MaskedPatient, idx: number) => {
                const isSelected = selected === match.external_patient_id;
                const initials = (match.first_name?.[0] || "?").toUpperCase();
                return (
                  <button
                    key={match.external_patient_id}
                    onClick={() => setSelected(match.external_patient_id)}
                    className={`w-full text-left rounded-xl border-2 p-4 transition-all duration-200 ${
                      isSelected
                        ? "border-ai-500 bg-ai-50 shadow-md"
                        : "border-gray-100 bg-gray-50 hover:border-ai-300 hover:bg-white hover:shadow-sm"
                    }`}
                    style={{ animationDelay: `${idx * 0.07}s` }}
                  >
                    <div className="flex items-center gap-3">
                      {/* Avatar */}
                      <div
                        className={`h-10 w-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0 transition-all ${
                          isSelected
                            ? "bg-ai-500 text-white shadow-lg"
                            : "bg-ai-100 text-ai-700"
                        }`}
                      >
                        {initials}
                      </div>

                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-gray-800 text-sm">
                          {match.first_name} {match.last_name}
                        </p>
                        <p className="text-xs text-gray-500 mt-0.5">DOB: {match.dob}</p>
                        {match.phone && (
                          <p className="text-xs text-gray-400">Phone: {match.phone}</p>
                        )}
                      </div>

                      {/* Selected check or mock badge */}
                      <div className="shrink-0 flex flex-col items-end gap-1">
                        {match.is_mock && (
                          <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full">
                            mock
                          </span>
                        )}
                        {isSelected && (
                          <div className="h-5 w-5 rounded-full bg-ai-500 flex items-center justify-center">
                            <svg
                              className="h-3 w-3 text-white"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth={3}
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M4.5 12.75l6 6 9-13.5"
                              />
                            </svg>
                          </div>
                        )}
                      </div>
                    </div>

                    {isSelected && (
                      <p className="mt-2 text-xs text-ai-600 font-medium ml-[52px]">
                        This looks like me — continue with this record
                      </p>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-2.5 text-sm mb-4">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="space-y-2">
            {selected && (
              <button
                onClick={handleConfirm}
                disabled={loading}
                className="w-full rounded-xl py-3 text-sm font-semibold text-white transition-all disabled:opacity-50"
                style={{ background: "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)" }}
              >
                {loading ? "Starting session…" : "Yes, that's me — Continue"}
              </button>
            )}
            <button
              onClick={() => router.push("/")}
              className="w-full border border-gray-200 text-gray-600 rounded-xl py-2.5 text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              Search again
            </button>
            <button
              onClick={handleManual}
              disabled={loading}
              className="w-full border border-gray-200 text-gray-500 rounded-xl py-2.5 text-sm font-medium hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              Continue without pre-fill (manual mode)
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
