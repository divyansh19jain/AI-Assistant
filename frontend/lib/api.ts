import type {
  PatientSearchResponse,
  SessionState,
  AnswerResult,
  ReviewResponse,
  GeneratePdfResponse,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  searchPatient: (body: {
    first_name: string;
    last_name: string;
    dob: string;
    consent: boolean;
  }): Promise<PatientSearchResponse> =>
    request("/api/patient/search", { method: "POST", body: JSON.stringify(body) }),

  createSession: (body: {
    patient_id?: string | null;
    form_id?: string;
    manual_mode?: boolean;
  }): Promise<SessionState> =>
    request("/api/session/create", { method: "POST", body: JSON.stringify(body) }),

  getSession: (sessionId: string): Promise<SessionState> =>
    request(`/api/session/${sessionId}`),

  submitAnswer: (
    sessionId: string,
    body: { field_key: string; raw_answer: string; input_mode: string; confirmed?: boolean }
  ): Promise<AnswerResult> =>
    request(`/api/session/${sessionId}/answer`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  skipField: (
    sessionId: string,
    body: { field_key: string; raw_answer: string; input_mode: string }
  ): Promise<AnswerResult> =>
    request(`/api/session/${sessionId}/skip`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  goBack: (sessionId: string): Promise<SessionState> =>
    request(`/api/session/${sessionId}/back`, { method: "POST" }),

  getReview: (sessionId: string): Promise<ReviewResponse> =>
    request(`/api/session/${sessionId}/review`),

  generatePdf: (sessionId: string): Promise<GeneratePdfResponse> =>
    request(`/api/session/${sessionId}/generate-pdf`, { method: "POST" }),

  downloadPdfUrl: (sessionId: string): string =>
    `${API_BASE}/api/session/${sessionId}/download-pdf`,

  tts: async (text: string): Promise<ArrayBuffer | null> => {
    try {
      const res = await fetch(`${API_BASE}/api/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok || res.status === 503) return null;
      const buf = await res.arrayBuffer();
      return buf.byteLength > 0 ? buf : null;
    } catch {
      return null;
    }
  },
};
