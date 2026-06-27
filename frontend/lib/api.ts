import type {
  PatientSearchResponse,
  SessionState,
  AnswerResult,
  ReviewResponse,
  GeneratePdfResponse,
  FormInfo,
  FormSummary,
  FormDetail,
  FormSchemaDoc,
  KbDocSummary,
  SkillCatalogItem,
  WorkflowState,
} from "./types";

// `??` (not `||`) so an explicitly-empty NEXT_PUBLIC_API_BASE_URL means "call the
// backend same-origin via the Next /api proxy". Unset (native dev) still falls back
// to localhost; an absolute URL (split-domain) is used directly.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TTS_TIMEOUT_MS = 15000;

export interface AgentTurn {
  assistant_message: string;
  done: boolean;
  go_to_review: boolean;
  state: {
    answered_count: number;
    missing_count: number;
    missing_required_count: number;
    total: number;
    next_field_key: string | null;
  };
  answers: Record<string, unknown>;
}

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

// ── Authenticated admin requests ───────────────────────────────────────────
// The builder UI calls /api/admin/* with the JWT stored in localStorage by the
// admin login page. On 401/403 we clear the token and bounce to /admin so an
// expired session never leaves the builder in a broken state.
function adminHeaders(): HeadersInit {
  const token = typeof window !== "undefined" ? localStorage.getItem("admin_token") : null;
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function adminRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: adminHeaders(), ...options });
  if (res.status === 401 || res.status === 403) {
    if (typeof window !== "undefined") {
      localStorage.removeItem("admin_token");
      window.location.href = "/admin";
    }
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as T; // DELETE
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

  // Conversational agent turn: send what the person said (typed or transcribed),
  // get the assistant's spoken reply + updated form state.
  agent: (sessionId: string, message: string, inputMode: string = "voice"): Promise<AgentTurn> =>
    request(`/api/session/${sessionId}/agent`, {
      method: "POST",
      body: JSON.stringify({ message, input_mode: inputMode }),
      // Never spin forever on a stuck turn — surface an error instead.
      signal: AbortSignal.timeout(45000),
    }),

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

  tts: async (text: string, formId?: string): Promise<ArrayBuffer | null> => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), TTS_TIMEOUT_MS);
    try {
      const res = await fetch(`${API_BASE}/api/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, form_id: formId }),
        signal: controller.signal,
      });
      if (!res.ok || res.status === 503) return null;
      const buf = await res.arrayBuffer();
      return buf.byteLength > 0 ? buf : null;
    } catch {
      return null;
    } finally {
      clearTimeout(timeout);
    }
  },

  // Public form catalog for the patient-flow form picker.
  listForms: (): Promise<{ forms: FormInfo[] }> => request("/api/forms"),

  // Approval gate + completion workflow (patient-facing).
  approveSession: (
    sessionId: string,
    body: { approved_by?: string; note?: string } = {}
  ): Promise<WorkflowState> =>
    request(`/api/session/${sessionId}/approve`, { method: "POST", body: JSON.stringify(body) }),
  getWorkflowStatus: (sessionId: string): Promise<WorkflowState> =>
    request(`/api/session/${sessionId}/workflow`),

  // Builder CRUD (admin-only; JWT injected by adminRequest).
  admin: {
    listForms: (): Promise<FormSummary[]> => adminRequest("/api/admin/forms"),
    getForm: (id: string): Promise<FormDetail> => adminRequest(`/api/admin/forms/${id}`),
    createForm: (body: {
      form_id: string;
      title: string;
      version?: string;
      output_targets?: string[];
    }): Promise<FormDetail> =>
      adminRequest("/api/admin/forms", { method: "POST", body: JSON.stringify(body) }),
    updateFormMeta: (
      id: string,
      body: { title?: string; version?: string; output_targets?: string[] }
    ): Promise<FormDetail> =>
      adminRequest(`/api/admin/forms/${id}`, { method: "PUT", body: JSON.stringify(body) }),
    updateFormSchema: (id: string, schema: FormSchemaDoc): Promise<FormDetail> =>
      adminRequest(`/api/admin/forms/${id}/schema`, {
        method: "PUT",
        body: JSON.stringify({ schema }),
      }),
    updateFormPrompts: (
      id: string,
      body: { prompt?: Record<string, unknown>; voice?: Record<string, unknown> }
    ): Promise<FormDetail> =>
      adminRequest(`/api/admin/forms/${id}/prompts`, { method: "PUT", body: JSON.stringify(body) }),
    publishForm: (id: string): Promise<FormDetail> =>
      adminRequest(`/api/admin/forms/${id}/publish`, { method: "POST" }),
    unpublishForm: (id: string): Promise<FormDetail> =>
      adminRequest(`/api/admin/forms/${id}/unpublish`, { method: "POST" }),
    deleteForm: (id: string): Promise<void> =>
      adminRequest(`/api/admin/forms/${id}`, { method: "DELETE" }),

    // Knowledgebase
    listKb: (id: string): Promise<KbDocSummary[]> => adminRequest(`/api/admin/forms/${id}/kb`),
    createKb: (id: string, body: { title: string; text: string; source?: string }): Promise<KbDocSummary> =>
      adminRequest(`/api/admin/forms/${id}/kb`, { method: "POST", body: JSON.stringify(body) }),
    reembedKb: (id: string, docId: number): Promise<KbDocSummary> =>
      adminRequest(`/api/admin/forms/${id}/kb/${docId}/reembed`, { method: "POST" }),
    deleteKb: (id: string, docId: number): Promise<void> =>
      adminRequest(`/api/admin/forms/${id}/kb/${docId}`, { method: "DELETE" }),

    // Skills (reusable AI capabilities)
    listSkillCatalog: (): Promise<SkillCatalogItem[]> => adminRequest(`/api/admin/skills`),
    getFormSkills: (id: string): Promise<{ attached: string[] }> =>
      adminRequest(`/api/admin/forms/${id}/skills`),
    setFormSkills: (id: string, skill_keys: string[]): Promise<{ attached: string[] }> =>
      adminRequest(`/api/admin/forms/${id}/skills`, { method: "PUT", body: JSON.stringify({ skill_keys }) }),
    updateFormWorkflow: (id: string, workflow: Record<string, unknown>): Promise<FormDetail> =>
      adminRequest(`/api/admin/forms/${id}/workflow`, { method: "PUT", body: JSON.stringify({ workflow }) }),
  },
};
