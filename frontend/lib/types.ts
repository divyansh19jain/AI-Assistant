export interface MaskedPatient {
  external_patient_id: string;
  first_name: string;
  last_name: string;
  dob: string;
  phone?: string;
  is_mock: boolean;
}

export interface PatientSearchResponse {
  matches: MaskedPatient[];
  count: number;
  is_mock: boolean;
  message?: string;
}

export interface SessionFieldSummary {
  field_key: string;
  label: string;
  value: unknown;
  source: string;
  section: string;
  is_sensitive: boolean;
}

export interface NextQuestion {
  field: {
    field_key: string;
    label: string;
    type: string;
    required: boolean;
    sensitive: boolean;
    question_text: string;
    validation_rule: Record<string, unknown>;
    depends_on: unknown;
    section: string;
  };
  question: string;
  missing_count: number;
  field_key: string;
  field_type: string;
  is_sensitive: boolean;
  is_optional: boolean;
}

export interface SessionState {
  session_id: string;
  form_id: string;
  status: string;
  mock_mode: boolean;
  prefilled_count: number;
  answered_count: number;
  missing_count: number;
  total_required: number;
  next_question: NextQuestion | null;
  prefilled_fields: SessionFieldSummary[];
  answers: Record<string, unknown>;
}

export interface AnswerResult {
  success: boolean;
  error?: string;
  acknowledgment?: string;
  extracted_value?: unknown;
  confidence?: number;
  needs_clarification?: boolean;
  is_command?: boolean;
  needs_confirmation?: boolean;
  pending_value?: unknown;
  next_question?: NextQuestion | null;
  is_complete?: boolean;
  missing_count?: number;
  answers?: Record<string, unknown>;
}

export interface ReviewField {
  field_key: string;
  label: string;
  value: unknown;
  source: string;
  section: string;
  section_title: string;
  is_sensitive: boolean;
  is_required: boolean;
}

export interface ReviewResponse {
  session_id: string;
  sections: Record<string, ReviewField[]>;
  missing_required: string[];
  is_complete: boolean;
}

export interface GeneratePdfResponse {
  session_id: string;
  download_url: string;
  file_name: string;
  is_fallback: boolean;
}
