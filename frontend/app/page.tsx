"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { CLINICAL_BATTERY_FORM_ID, MEDICAID_FORM_ID, clinicalTools, estimatedClinicalMinutes, selectedToolGateAnswers } from "@/lib/clinical";
import type { FormInfo } from "@/lib/types";

type FlowMode = "medicaid" | "clinical";

export default function LandingPage() {
  const router = useRouter();
  const [mode, setMode] = useState<FlowMode>("medicaid");
  const [consent, setConsent] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [dob, setDob] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forms, setForms] = useState<FormInfo[]>([]);
  const [selectedFormId, setSelectedFormId] = useState<string>(MEDICAID_FORM_ID);
  const [selectedClinicalTools, setSelectedClinicalTools] = useState<string[]>(["phq9", "gad7", "cssrs"]);

  useEffect(() => {
    api
      .listForms()
      .then(({ forms }) => {
        setForms(forms);
        const storedForm = sessionStorage.getItem("selectedFormId");
        const storedMode = sessionStorage.getItem("selectedFlowMode") as FlowMode | null;
        const storedTools = sessionStorage.getItem("selectedClinicalTools");
        setMode(storedMode === "clinical" ? "clinical" : "medicaid");
        setSelectedFormId(
          storedForm && forms.some((f) => f.form_id === storedForm)
            ? storedForm
            : forms.find((f) => f.form_id === MEDICAID_FORM_ID)?.form_id ?? forms[0]?.form_id ?? MEDICAID_FORM_ID
        );
        if (storedTools) {
          const parsed = JSON.parse(storedTools) as string[];
          const allowed = new Set(clinicalTools.map((tool) => tool.key));
          const filtered = parsed.filter((key) => allowed.has(key));
          if (filtered.length) setSelectedClinicalTools(filtered);
        }
      })
      .catch(() => {
        /* Keep local defaults if the catalog is temporarily unavailable. */
      });
  }, []);

  const medicaidForm = forms.find((f) => f.form_id === selectedFormId || f.form_id === MEDICAID_FORM_ID);
  const clinicalEstimate = useMemo(() => estimatedClinicalMinutes(selectedClinicalTools), [selectedClinicalTools]);
  const activeFormId = mode === "clinical" ? CLINICAL_BATTERY_FORM_ID : selectedFormId || MEDICAID_FORM_ID;

  useEffect(() => {
    sessionStorage.setItem("selectedFlowMode", mode);
    sessionStorage.setItem("selectedFormId", activeFormId);
    sessionStorage.setItem("selectedClinicalTools", JSON.stringify(selectedClinicalTools));
  }, [mode, activeFormId, selectedClinicalTools]);

  function toggleClinicalTool(key: string) {
    setSelectedClinicalTools((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key]
    );
  }

  function initialAnswers() {
    return mode === "clinical" ? selectedToolGateAnswers(selectedClinicalTools) : undefined;
  }

  function validateStart(): boolean {
    if (mode === "clinical" && selectedClinicalTools.length === 0) {
      setError("Select at least one clinical assessment.");
      return false;
    }
    return true;
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!validateStart()) return;
    if (!consent) {
      setError("Consent is required before searching EMR records.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await api.searchPatient({
        first_name: firstName,
        last_name: lastName,
        dob,
        consent: true,
      });
      sessionStorage.setItem("patientSearchResult", JSON.stringify(result));
      sessionStorage.setItem("patientSearchInput", JSON.stringify({ firstName, lastName, dob }));
      sessionStorage.setItem("selectedFlowMode", mode);
      sessionStorage.setItem("selectedFormId", activeFormId);
      sessionStorage.setItem("selectedClinicalTools", JSON.stringify(selectedClinicalTools));
      router.push("/patient-match");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleManualContinue() {
    if (!validateStart()) return;
    setLoading(true);
    setError(null);
    try {
      const session = await api.createSession({
        manual_mode: true,
        form_id: activeFormId,
        initial_answers: initialAnswers(),
      });
      router.push(`/assistant/${session.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start session.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-[100dvh] bg-slate-50 text-slate-900">
      <div className="mx-auto flex min-h-[100dvh] w-full max-w-6xl flex-col px-4 py-6 sm:px-6 lg:px-8">
        <header className="mb-5 flex flex-col gap-2 sm:mb-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-slate-900 text-sm font-bold text-white">
              AI
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-normal text-slate-950 sm:text-3xl">
                AI Form Assistant
              </h1>
              <p className="text-sm text-slate-600 sm:text-base">
                Choose a form path, match the client record, then complete the session by voice or touch.
              </p>
            </div>
          </div>
        </header>

        <section className="grid flex-1 gap-5 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                {
                  key: "medicaid" as FlowMode,
                  title: "Medicaid Application",
                  detail: medicaidForm?.title ?? "Ohio Medicaid Application",
                  meta: "Benefits application with PDF completion",
                },
                {
                  key: "clinical" as FlowMode,
                  title: "Clinical Forms",
                  detail: `${selectedClinicalTools.length} assessment${selectedClinicalTools.length === 1 ? "" : "s"} selected`,
                  meta: `Self-report tools, ${clinicalEstimate}`,
                },
              ].map((option) => {
                const selected = mode === option.key;
                return (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => {
                      setMode(option.key);
                      setError(null);
                    }}
                    className={`min-h-[112px] rounded-lg border-2 p-4 text-left transition-colors ${
                      selected
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-800 hover:border-slate-400"
                    }`}
                  >
                    <span className="block text-lg font-semibold">{option.title}</span>
                    <span className={`mt-2 block text-sm ${selected ? "text-slate-100" : "text-slate-600"}`}>
                      {option.detail}
                    </span>
                    <span className={`mt-1 block text-xs ${selected ? "text-slate-300" : "text-slate-500"}`}>
                      {option.meta}
                    </span>
                  </button>
                );
              })}
            </div>

            {mode === "clinical" ? (
              <div className="mt-5">
                <div className="mb-3 flex items-end justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold text-slate-950">Select Clinical Assessments</h2>
                    <p className="text-sm text-slate-600">Large touch targets work well on iPad. Scores calculate after review.</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedClinicalTools(clinicalTools.map((tool) => tool.key))}
                    className="min-h-11 rounded-lg border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-100"
                  >
                    Select all
                  </button>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {clinicalTools.map((tool) => {
                    const selected = selectedClinicalTools.includes(tool.key);
                    return (
                      <button
                        key={tool.key}
                        type="button"
                        onClick={() => toggleClinicalTool(tool.key)}
                        className={`min-h-[116px] rounded-lg border-2 p-4 text-left transition-colors ${
                          selected
                            ? "border-teal-600 bg-teal-50"
                            : "border-slate-200 bg-white hover:border-slate-400"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <span className="block text-base font-semibold text-slate-950">{tool.shortName}</span>
                            <span className="mt-1 block text-sm text-slate-600">{tool.description}</span>
                          </div>
                          <span
                            className={`flex h-8 min-w-8 items-center justify-center rounded-lg border text-sm font-bold ${
                              selected ? "border-teal-600 bg-teal-600 text-white" : "border-slate-300 text-slate-400"
                            }`}
                          >
                            {selected ? "On" : ""}
                          </span>
                        </div>
                        <span className="mt-3 block text-xs font-semibold uppercase tracking-wide text-slate-500">
                          {tool.estimate}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <h2 className="text-lg font-semibold text-slate-950">Ohio Medicaid Application</h2>
                <p className="mt-1 text-sm text-slate-600">
                  The assistant will help gather household, income, insurance, and program details, then produce the Medicaid PDF workflow.
                </p>
              </div>
            )}
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <h2 className="text-lg font-semibold text-slate-950">Client Lookup</h2>
            <p className="mt-1 text-sm text-slate-600">
              Search the EMR first, or continue manually and let the assistant ask for missing identity details.
            </p>

            <form onSubmit={handleSearch} className="mt-4 space-y-4">
              <label className="flex min-h-[64px] cursor-pointer items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3.5">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="mt-1 h-5 w-5 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
                />
                <span className="text-sm leading-snug text-amber-950">
                  <strong>I consent</strong> to searching EMR records to match and pre-fill this session.
                </span>
              </label>

              {[
                { label: "First Name", value: firstName, setValue: setFirstName, type: "text", placeholder: "Enter first name" },
                { label: "Last Name", value: lastName, setValue: setLastName, type: "text", placeholder: "Enter last name" },
                { label: "Date of Birth", value: dob, setValue: setDob, type: "date", placeholder: "" },
              ].map((field) => (
                <div key={field.label}>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-600">
                    {field.label}
                  </label>
                  <input
                    type={field.type}
                    value={field.value}
                    onChange={(e) => field.setValue(e.target.value)}
                    required
                    placeholder={field.placeholder}
                    className="min-h-12 w-full rounded-lg border border-slate-300 px-4 text-base text-slate-900 outline-none transition focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
                  />
                </div>
              ))}

              {error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading || !consent}
                className="min-h-12 w-full rounded-lg bg-slate-900 px-4 text-base font-semibold text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? "Searching records..." : "Search EMR Records"}
              </button>
            </form>

            <div className="my-4 flex items-center gap-3">
              <div className="h-px flex-1 bg-slate-200" />
              <span className="text-xs text-slate-500">or</span>
              <div className="h-px flex-1 bg-slate-200" />
            </div>

            <button
              onClick={handleManualContinue}
              disabled={loading}
              className="min-h-12 w-full rounded-lg border border-slate-300 px-4 text-base font-semibold text-slate-700 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Continue Without EMR Lookup
            </button>

            <p className="mt-4 text-xs leading-relaxed text-slate-500">
              Clinical scores are screening summaries, not diagnoses. Review all answers and scores before PDF generation or EMR export.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}
