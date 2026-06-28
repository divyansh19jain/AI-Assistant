"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { FormInfo } from "@/lib/types";

export default function LandingPage() {
  const router = useRouter();
  const [consent, setConsent] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [dob, setDob] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The form the patient is completing. Loaded from the published catalog; the
  // choice is carried to /patient-match (and the manual flow) via sessionStorage.
  const [forms, setForms] = useState<FormInfo[]>([]);
  const [selectedFormId, setSelectedFormId] = useState<string>("");

  useEffect(() => {
    api
      .listForms()
      .then(({ forms }) => {
        setForms(forms);
        const stored = typeof window !== "undefined" ? sessionStorage.getItem("selectedFormId") : null;
        setSelectedFormId(stored && forms.some((f) => f.form_id === stored) ? stored : forms[0]?.form_id ?? "");
      })
      .catch(() => {
        /* leave empty — backend default form applies if the catalog can't load */
      });
  }, []);

  useEffect(() => {
    if (selectedFormId && typeof window !== "undefined") sessionStorage.setItem("selectedFormId", selectedFormId);
  }, [selectedFormId]);

  const selectedForm = forms.find((f) => f.form_id === selectedFormId);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!consent) {
      setError("You must provide consent to search the EMR database.");
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
      router.push("/patient-match");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleManualContinue() {
    setLoading(true);
    try {
      const session = await api.createSession({ manual_mode: true, form_id: selectedFormId || undefined });
      router.push(`/assistant/${session.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start session.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-[100dvh] flex flex-col items-center justify-start sm:justify-center px-4 py-8 sm:py-10"
      style={{ background: "linear-gradient(160deg,#f8faff 0%,#eef2ff 50%,#f5f3ff 100%)", paddingTop: "max(2rem, env(safe-area-inset-top))", paddingBottom: "max(2rem, env(safe-area-inset-bottom))" }}>
      {/* Hero section */}
      <div className="text-center mb-6 sm:mb-10 animate-fade-slide-up">
        {/* Large AI orb */}
        <div className="relative mx-auto mb-6 h-24 w-24">
          <div className="absolute inset-0 rounded-full ai-orb" />
          <div className="relative z-10 h-full w-full flex items-center justify-center">
            <svg
              className="h-10 w-10 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"
              />
            </svg>
          </div>
        </div>

        <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold text-gray-900 mb-2">
          Hi, I&apos;m your AI Form Assistant
        </h2>
        <p className="text-gray-500 text-base md:text-lg max-w-md md:max-w-lg mx-auto">
          I&apos;ll help you complete the selected form by finding your records and
          asking only the questions that still need answers.
        </p>
      </div>

      {/* Card */}
      <div
        className="w-full max-w-md md:max-w-xl bg-white rounded-2xl shadow-xl border border-gray-100 p-6 sm:p-8 md:p-10 animate-fade-slide-up"
        style={{ animationDelay: "0.1s" }}
      >
        {/* Form picker — populated from the published catalog (GET /api/forms). */}
        <div className="mb-6">
          <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
            Which form?
          </label>
          {forms.length > 1 ? (
            <select
              value={selectedFormId}
              onChange={(e) => setSelectedFormId(e.target.value)}
              className="w-full border border-gray-200 rounded-xl px-4 py-3 text-base text-gray-800 focus:outline-none focus:ring-2 focus:ring-ai-400 focus:border-transparent"
            >
              {forms.map((f) => (
                <option key={f.form_id} value={f.form_id}>
                  {f.title}
                </option>
              ))}
            </select>
          ) : (
            <div className="flex items-center gap-2">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-ai-500" />
              <span className="text-sm font-semibold text-gray-800">
                {selectedForm?.title ?? "Ohio Medicaid Application"}
              </span>
            </div>
          )}
        </div>

        {/* How it works */}
        <div className="bg-ai-50 border border-ai-100 rounded-xl p-4 mb-6">
          <p className="text-xs font-semibold text-ai-700 mb-2 uppercase tracking-wide">
            How it works
          </p>
          <div className="space-y-1.5">
            {[
              "Enter your name and date of birth below",
              "We search your EMR records to pre-fill the form",
              "Your AI assistant asks only the missing questions",
              "Review, approve, and complete the form workflow",
            ].map((step, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="mt-0.5 h-5 w-5 rounded-full bg-ai-500 text-white text-xs font-bold flex items-center justify-center shrink-0">
                  {i + 1}
                </span>
                <span className="text-sm text-ai-800">{step}</span>
              </div>
            ))}
          </div>
        </div>

        <form onSubmit={handleSearch} className="space-y-4">
          {/* Consent */}
          <label className="flex items-start gap-3 cursor-pointer bg-amber-50 border border-amber-200 rounded-xl p-3.5 hover:bg-amber-100 transition-colors">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 h-5 w-5 rounded border-gray-300 text-ai-500 focus:ring-ai-400"
            />
            <span className="text-sm text-amber-900 leading-snug">
              <strong>I consent</strong> to searching the EMR database for my patient records to
              pre-fill this form. Results will be masked for privacy.
            </span>
          </label>

          {/* First Name */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
              First Name
            </label>
            <input
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              required
              className="w-full border border-gray-200 rounded-xl px-4 py-3 text-base text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-ai-400 focus:border-transparent transition-shadow"
              placeholder="Enter first name"
            />
          </div>

          {/* Last Name */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
              Last Name
            </label>
            <input
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              required
              className="w-full border border-gray-200 rounded-xl px-4 py-3 text-base text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-ai-400 focus:border-transparent transition-shadow"
              placeholder="Enter last name"
            />
          </div>

          {/* Date of Birth */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
              Date of Birth
            </label>
            <input
              type="date"
              value={dob}
              onChange={(e) => setDob(e.target.value)}
              required
              className="w-full border border-gray-200 rounded-xl px-4 py-3 text-base text-gray-800 focus:outline-none focus:ring-2 focus:ring-ai-400 focus:border-transparent transition-shadow"
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-2.5 text-sm">
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading || !consent}
            className="w-full relative overflow-hidden rounded-xl py-3 md:py-3.5 text-sm md:text-base font-semibold text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background:
                "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
            }}
          >
            <span className="relative z-10">
              {loading ? "Searching records…" : "Search My Records"}
            </span>
          </button>
        </form>

        <div className="mt-4 flex items-center gap-3">
          <div className="flex-1 h-px bg-gray-100" />
          <span className="text-xs text-gray-400">or</span>
          <div className="flex-1 h-px bg-gray-100" />
        </div>

        <button
          onClick={handleManualContinue}
          disabled={loading}
          className="w-full mt-3 border border-gray-200 text-gray-600 hover:bg-gray-50 rounded-xl py-3 md:py-3.5 text-sm md:text-base font-medium transition-colors disabled:opacity-50"
        >
          Continue without EMR lookup (manual mode)
        </button>
      </div>

      <p className="mt-8 text-xs text-center text-gray-400 max-w-sm">
        This assistant helps complete the form but does not determine eligibility or provide
        legal advice. Please review all answers before using the generated PDF.
      </p>
    </div>
  );
}
