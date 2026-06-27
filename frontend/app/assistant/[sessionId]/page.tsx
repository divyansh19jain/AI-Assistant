"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useVoice } from "@/lib/useVoice";
import type { SessionState, AnswerResult, ReviewResponse, ReviewField } from "@/lib/types";

/* ─── Message model ───────────────────────────────────────────────── */
interface Message {
  id: string;
  role: "ai" | "user";
  text: string;
  type?: "question" | "answer" | "clarification" | "complete";
  fieldKey?: string;    // for "answer" bubbles — which field this answered
  fieldType?: string;   // so the edit input renders the right control
  isSensitive?: boolean;
}

let _id = Date.now(); // start from a large value so restored IDs never collide
function uid() { return String(++_id); }

function storageKey(sessionId: string) { return `chat_messages_${sessionId}`; }

function saveMessages(sessionId: string, msgs: Message[]) {
  try { localStorage.setItem(storageKey(sessionId), JSON.stringify(msgs)); } catch { /* quota */ }
}

function loadMessages(sessionId: string): Message[] | null {
  try {
    const raw = localStorage.getItem(storageKey(sessionId));
    return raw ? (JSON.parse(raw) as Message[]) : null;
  } catch { return null; }
}

/* ─── Small orb (used in chat bubbles) ───────────────────────────── */
function MiniOrb({ size = 32 }: { size?: number }) {
  return (
    <div
      className="ai-orb shrink-0 flex items-center justify-center rounded-full"
      style={{ width: size, height: size }}
    >
      <svg style={{ width: size * 0.42, height: size * 0.42 }} fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round"
          d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
      </svg>
    </div>
  );
}

/* ─── Typing indicator ────────────────────────────────────────────── */
function TypingIndicator() {
  return (
    <div className="flex items-end gap-2.5">
      <MiniOrb size={30} />
      <div className="bubble-ai flex items-center gap-1.5 py-3">
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </div>
    </div>
  );
}

/* ─── Left panel: big orb + waveform ─────────────────────────────── */
function LeftPanel({
  mode,
  progress,
  missing,
  mockMode,
  autoSpeak,
  onToggleSpeak,
  onStopSpeak,
  onToggleMic,
  voiceSupported,
  isSensitive,
  submitting,
  sessionId,
  formTitle,
}: {
  mode: "idle" | "speaking" | "listening";
  progress: number;
  missing: number;
  mockMode?: boolean;
  autoSpeak: boolean;
  onToggleSpeak: () => void;
  onStopSpeak: () => void;
  onToggleMic: () => void;
  voiceSupported: boolean;
  isSensitive: boolean;
  submitting: boolean;
  sessionId: string;
  formTitle: string;
}) {
  const router = useRouter();

  const statusLabel =
    mode === "speaking" ? "Speaking…" :
    mode === "listening" ? "Listening…" :
    "Ready";

  const statusColor =
    mode === "speaking" ? "#818cf8" :
    mode === "listening" ? "#fb7185" :
    "#64748b";

  return (
    <div
      className="relative flex flex-col items-center justify-between h-full px-5 py-7 overflow-hidden"
      style={{ background: "linear-gradient(160deg,#0a0f1e 0%,#0f172a 60%,#131d35 100%)" }}
    >
      {/* Subtle radial glow behind orb */}
      <div
        className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-20"
        style={{
          width: 340, height: 340,
          background: mode === "listening"
            ? "radial-gradient(circle,#dc2626 0%,transparent 70%)"
            : "radial-gradient(circle,#4f46e5 0%,transparent 70%)",
          transition: "background 0.6s ease",
        }}
      />

      {/* Top: brand + mock badge */}
      <div className="w-full flex items-center justify-between z-10">
        <div>
          <p className="text-white text-sm font-bold tracking-tight">AI Form Assistant</p>
          <p className="text-slate-600 text-[11px] truncate max-w-[180px]">{formTitle}</p>
        </div>
        {mockMode && (
          <span className="text-[10px] bg-amber-500/15 text-amber-400 border border-amber-500/25 px-2 py-0.5 rounded-full">
            MOCK
          </span>
        )}
      </div>

      {/* Center: orb + rings + waveform */}
      <div className="flex flex-col items-center gap-8 z-10">

        {/* Orb with pulse rings */}
        <div className="relative" style={{ width: 140, height: 140 }}>
          {mode === "speaking" && (
            <>
              <span className="pulse-ring" />
              <span className="pulse-ring" />
              <span className="pulse-ring" />
            </>
          )}
          <div
            className="ai-orb absolute inset-0 rounded-full z-10 flex items-center justify-center"
            style={{ width: 140, height: 140 }}
          >
            {mode === "listening" ? (
              <div className="flex items-end gap-[4px]" style={{ height: 52 }}>
                {[10, 18, 26, 18, 10].map((h, i) => (
                  <span key={i} className="wave-bar" style={{ height: h }} />
                ))}
              </div>
            ) : (
              <svg width="54" height="54" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            )}
          </div>
        </div>

        {/* Status label */}
        <div className="flex flex-col items-center gap-1.5">
          <span
            className="text-sm font-semibold tracking-wide transition-colors duration-300"
            style={{ color: statusColor }}
          >
            {statusLabel}
          </span>
          <div className="flex items-center gap-1.5">
            <div
              className="h-1.5 w-1.5 rounded-full transition-colors duration-300"
              style={{ background: statusColor, boxShadow: mode !== "idle" ? `0 0 6px ${statusColor}` : "none" }}
            />
            <span className="text-[11px] text-slate-600">
              {mode === "idle" ? "Waiting for your answer" :
               mode === "speaking" ? "Listen to the question" :
               "Speak your answer now"}
            </span>
          </div>
        </div>

        {/* Waveform visualizer */}
        {mode !== "idle" && (
          <div className={`wave-viz ${mode} anim-fade-up`}>
            {Array.from({ length: 20 }).map((_, i) => (
              <div key={i} className="wave-viz-bar" />
            ))}
          </div>
        )}

        {/* Idle placeholder bars — static, muted */}
        {mode === "idle" && (
          <div className="flex items-end justify-center gap-[5px]" style={{ height: 64 }}>
            {[12, 22, 32, 44, 56, 44, 56, 44, 36, 28, 44, 56, 48, 36, 24, 40, 52, 38, 22, 14].map((h, i) => (
              <div
                key={i}
                style={{
                  width: 5, height: h,
                  borderRadius: 9999,
                  background: "rgba(99,102,241,0.15)",
                }}
              />
            ))}
          </div>
        )}

        {/* Voice control buttons */}
        {voiceSupported && (
          <div className="flex items-center gap-3 mt-1">
            {/* Mic toggle */}
            <button
              onClick={onToggleMic}
              disabled={mode === "speaking" || submitting || isSensitive}
              title={isSensitive ? "Voice disabled for sensitive fields" : mode === "listening" ? "Stop listening" : "Start listening"}
              className={`flex items-center justify-center w-12 h-12 rounded-2xl transition-all ${
                mode === "listening"
                  ? "bg-red-500 text-white shadow-xl shadow-red-900/60"
                  : mode === "speaking" || isSensitive
                  ? "bg-slate-800/60 text-slate-700 border border-slate-800 cursor-not-allowed"
                  : "bg-slate-800/80 text-slate-400 border border-slate-700 hover:border-indigo-500 hover:text-indigo-400"
              }`}
            >
              {mode === "listening" ? (
                <svg width="18" height="18" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              ) : (
                <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
              )}
            </button>

            {/* Auto-speak toggle */}
            <button
              onClick={onToggleSpeak}
              title={autoSpeak ? "Disable auto-speak" : "Enable auto-speak"}
              className={`flex items-center gap-2 px-4 h-12 rounded-2xl text-xs font-medium border transition-all ${
                autoSpeak
                  ? "bg-indigo-600/20 border-indigo-500/40 text-indigo-300 hover:bg-indigo-600/30"
                  : "bg-slate-800/60 border-slate-700 text-slate-500 hover:border-slate-600 hover:text-slate-300"
              }`}
            >
              <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
              </svg>
              {autoSpeak ? "Voice On" : "Voice Off"}
            </button>

            {/* Stop speaking */}
            {mode === "speaking" && (
              <button
                onClick={onStopSpeak}
                className="flex items-center justify-center w-12 h-12 rounded-2xl bg-slate-800/80 border border-slate-700 text-slate-400 hover:border-red-500 hover:text-red-400 transition-all"
                title="Stop speaking"
              >
                <svg width="16" height="16" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="5" y="5" width="14" height="14" rx="2" />
                </svg>
              </button>
            )}
          </div>
        )}
      </div>

      {/* Bottom: progress + nav */}
      <div className="w-full z-10 space-y-3">
        {/* Progress bar */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-600">Form progress</span>
            <span className="text-[11px] text-slate-500 tabular-nums">{progress}%</span>
          </div>
          <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{ width: `${progress}%`, background: "linear-gradient(90deg,#6366f1,#8b5cf6)" }}
            />
          </div>
          <p className="text-[11px] text-slate-700 tabular-nums">
            {missing} field{missing !== 1 ? "s" : ""} remaining
          </p>
        </div>

        {/* Review link */}
        <button
          onClick={() => router.push(`/review/${sessionId}`)}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl border border-slate-800 text-xs text-slate-600 hover:text-slate-400 hover:border-slate-700 transition-all"
        >
          Go to review
          <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
          </svg>
        </button>
      </div>
    </div>
  );
}

/* ─── Fields panel (live form field list) ────────────────────────── */
function FieldsPanel({
  review,
  currentFieldKey,
}: {
  review: ReviewResponse | null;
  currentFieldKey?: string;
}) {
  if (!review) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-600">
        <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
        </svg>
        <span className="text-xs">Loading fields…</span>
      </div>
    );
  }

  const sections = Object.entries(review.sections);

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {sections.map(([sectionKey, fields]) => {
        const filled = fields.filter(
          (f) => f.value !== null && f.value !== undefined && f.source !== "skipped"
        ).length;
        const total = fields.length;

        return (
          <div key={sectionKey} className="mb-1">
            {/* Section header */}
            <div className="sticky top-0 z-10 px-4 py-2.5 flex items-center justify-between"
              style={{ background: "rgba(10,15,30,0.97)", backdropFilter: "blur(8px)" }}>
              <span className="text-xs font-bold tracking-widest uppercase text-indigo-400">
                {sectionKey.replace(/_/g, " ")}
              </span>
              <span className="text-xs text-slate-500 tabular-nums">{filled}/{total}</span>
            </div>

            {/* Fields */}
            <div className="divide-y divide-white/5">
              {fields.map((field: ReviewField) => {
                const isMissing = field.value === null || field.value === undefined;
                const isSkipped = field.source === "skipped";
                const isCurrent = field.field_key === currentFieldKey;

                let valueDisplay: string;
                if (field.is_sensitive && !isMissing && !isSkipped) {
                  valueDisplay = "•••••";
                } else if (isSkipped) {
                  valueDisplay = "Skipped";
                } else if (isMissing) {
                  valueDisplay = "Not provided";
                } else {
                  valueDisplay = String(field.value);
                }

                return (
                  <div
                    key={field.field_key}
                    className="px-4 py-3 transition-colors"
                    style={{
                      background: isCurrent ? "rgba(99,102,241,0.08)" : "transparent",
                      borderLeft: isCurrent ? "3px solid #6366f1" : "3px solid transparent",
                    }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-slate-400 leading-tight flex-1 min-w-0 truncate">
                        {field.label}
                        {!field.is_required && (
                          <span className="ml-1 text-[10px] text-slate-600">(opt)</span>
                        )}
                      </span>
                      {isCurrent ? (
                        <span className="shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-md bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                          Current
                        </span>
                      ) : isMissing && !isSkipped ? (
                        <span className="shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-md bg-red-500/20 text-red-400 border border-red-500/30">
                          Missing
                        </span>
                      ) : isSkipped ? (
                        <span className="shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-md bg-slate-700/60 text-slate-400 border border-slate-600/40">
                          Skipped
                        </span>
                      ) : (
                        <div className="shrink-0 flex items-center gap-1">
                          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">Filled</span>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#34d399" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
                        </div>
                      )}
                    </div>
                    <p className={`mt-0.5 text-xs font-medium truncate ${
                      isMissing && !isSkipped ? "text-red-400 italic" :
                      isSkipped ? "text-slate-500 italic" :
                      "text-white"
                    }`}>
                      {valueDisplay}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ─── Main page ───────────────────────────────────────────────────── */
export default function AssistantPage() {
  const router = useRouter();
  const { sessionId } = useParams() as { sessionId: string };

  const [session, setSession]     = useState<SessionState | null>(null);
  const [messages, setMessages]   = useState<Message[]>(() => loadMessages(sessionId) ?? []);
  const [answer, setAnswer]       = useState("");
  const [loading, setLoading]     = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showTyping, setShowTyping] = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [showTypeBox, setShowTypeBox] = useState(false);
  const [review, setReview]       = useState<ReviewResponse | null>(null);
  const [showFieldsPanel, setShowFieldsPanel] = useState(true);

  const bottomRef  = useRef<HTMLDivElement>(null);
  const inputRef   = useRef<HTMLInputElement>(null);
  const firstLoad  = useRef(false);
  const lastSpokenKey = useRef<string | null>(null);
  // When the assistant has read a value back and is waiting for yes/no
  // ("I heard X — is that right?"), this holds the field + pending value so the
  // next utterance is interpreted as a confirmation, not a fresh answer.
  const pendingConfirm = useRef<{ fieldKey: string; value: string } | null>(null);
  // Always points at the latest submit logic so voice capture can auto-submit
  // without stale-closure problems.
  const processAnswerRef = useRef<(text: string) => void>(() => {});
  // Live mirrors of state the async voice path needs — avoids stale closures
  // that would silently drop a spoken answer.
  const submittingRef = useRef(false);

  const {
    status: voiceStatus, supported: voiceSupported,
    speak, stopSpeaking, startListening, stopListening, clearTranscript, prefetchTts,
  } = useVoice({
    formId: session?.form_id,
    hint: session?.next_question
      ? session.next_question.field_type === "date"
        ? `${session.next_question.field.label}, date format MM/DD/YYYY, for example 01/15/1985, skip`
        : `${session.next_question.field.label}, ${session.next_question.field_type}, skip, yes, no`
      : "skip, yes, no",
    onTranscript: (t) => {
      setAnswer(t);
      setVoiceError(null);
      // Hands-free back-and-forth: auto-submit the spoken answer after a brief
      // pause so the user can see what was captured.
      setTimeout(() => processAnswerRef.current(t), 600);
    },
    onError: (m) => setVoiceError(m),
  });

  const isSpeaking   = voiceStatus === "speaking";
  const isListening  = voiceStatus === "listening";
  const isProcessing = voiceStatus === "processing";
  const orbMode      = isSpeaking ? "speaking" : isListening ? "listening" : "idle";

  /* persist chat history across refreshes */
  useEffect(() => {
    if (messages.length > 0) saveMessages(sessionId, messages);
  }, [messages, sessionId]);

  /* scroll chat to bottom */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, showTyping]);

  /* focus input when idle */
  useEffect(() => {
    if (!isListening && !isSpeaking) inputRef.current?.focus();
  }, [isListening, isSpeaking, messages]);

  /* load session */
  const loadSession = useCallback(async () => {
    try {
      const s = await api.getSession(sessionId);
      setSession(s);
    } catch {
      setError("Failed to load session.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const refreshReview = useCallback(async () => {
    try {
      const r = await api.getReview(sessionId);
      setReview(r);
    } catch {
      // non-critical — panel just shows stale data
    }
  }, [sessionId]);

  useEffect(() => { loadSession(); }, [loadSession]);
  useEffect(() => { refreshReview(); }, [refreshReview]);

  /* On new question: show bubble + speak simultaneously, or just show if voice off */
  useEffect(() => {
    if (!session?.next_question) return;
    const key = session.next_question.field_key;
    const q   = session.next_question.question;

    // First load: restore from localStorage or show immediately (no audio yet)
    if (!firstLoad.current) {
      firstLoad.current = true;
      const restored = messages.length > 0;
      if (!restored) {
        if (autoSpeak) {
          prefetchTts(q);
          const isSensitive = session.next_question.is_sensitive;
          const allowMic = !isSensitive || session.next_question.field_type === "date";
          lastSpokenKey.current = key;
          speak(q, allowMic ? () => { setTimeout(() => startListening(), 300); } : undefined,
            () => setMessages([{ id: uid(), role: "ai", text: q, type: "question" }]));
        } else {
          setMessages([{ id: uid(), role: "ai", text: q, type: "question" }]);
        }
      }
      return;
    }

    // Subsequent questions driven by session state change (e.g. external update)
    if (lastSpokenKey.current === key) return;
    lastSpokenKey.current = key;
    if (!autoSpeak) {
      setMessages(prev => [...prev, { id: uid(), role: "ai", text: q, type: "question" }]);
      return;
    }
    prefetchTts(q);
    const isSensitive = session.next_question.is_sensitive;
    const allowMic = !isSensitive || session.next_question.field_type === "date";
    speak(q, allowMic ? () => { setTimeout(() => startListening(), 300); } : undefined,
      () => setMessages(prev => [...prev, { id: uid(), role: "ai", text: q, type: "question" }]));
  }, [session?.next_question?.field_key]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Interpret a short utterance as yes / no / neither (for confirmations). */
  function yesNo(text: string): "yes" | "no" | null {
    const t = text.trim().toLowerCase().replace(/[.!?]/g, "");
    if (/\b(yes|yeah|yep|yup|correct|right|sure|that'?s right|confirm|ok|okay)\b/.test(t)) return "yes";
    if (/\b(no|nope|nah|wrong|incorrect|not right|that'?s wrong)\b/.test(t)) return "no";
    return null;
  }

  /* core submit — shared by the form and by voice auto-submit */
  async function processAnswer(rawText: string) {
    const text = rawText.trim();
    // Use the live ref (not captured `submitting`) so a voice answer fired from
    // a stale closure is never silently dropped.
    if (!session?.next_question || !text || submittingRef.current) return;
    const viaVoice = voiceStatus === "processing" || voiceStatus === "listening";

    // --- Smart-confirm: we're waiting for the user to confirm a read-back value ---
    const pc = pendingConfirm.current;
    if (pc && pc.fieldKey === session.next_question.field_key) {
      const yn = yesNo(text);
      if (yn === "yes") {
        pendingConfirm.current = null;
        // Resubmit the confirmed value with the confirmed flag so it saves.
        await submitConfirmed(pc.value, viaVoice);
        return;
      }
      if (yn === "no") {
        pendingConfirm.current = null;
        const reask = "No problem — let's try again. " + session.next_question.question;
        setMessages(prev => [...prev, { id: uid(), role: "ai", text: reask, type: "clarification" }]);
        if (autoSpeak) speak(reask, (session.next_question.is_sensitive && session.next_question.field_type !== "date") ? undefined : () => {
          setTimeout(() => startListening(), 300);
        });
        return;
      }
      // Neither yes nor no — fall through and treat as a fresh answer attempt.
      pendingConfirm.current = null;
    }
    const answeredKey = session.next_question.field_key;
    const answeredType = session.next_question.field_type;
    const answeredSensitive = session.next_question.is_sensitive;
    stopSpeaking();
    stopListening();
    clearTranscript();
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    setShowTypeBox(false);

    setMessages(prev => [...prev, {
      id: uid(), role: "user", text, type: "answer",
      fieldKey: answeredKey, fieldType: answeredType, isSensitive: answeredSensitive,
    }]);
    setAnswer("");

    try {
      const result: AnswerResult = await api.submitAnswer(sessionId, {
        field_key: session.next_question.field_key,
        raw_answer: text,
        input_mode: viaVoice ? "voice" : "typed",
      });

      // Stray UI/voice command word (e.g. "send") — ignore it silently, stay on
      // the same field, keep listening. Remove the echoed user bubble so it
      // doesn't look like we accepted it.
      if (result.is_command) {
        setMessages(prev => prev.filter(m => !(m.role === "user" && m.text === text && m.fieldKey === answeredKey)));
        if (autoSpeak) setTimeout(() => startListening(), 200);
        return;
      }

      // Smart-confirm: the assistant read the value back and is waiting for
      // yes/no. Arm the pending-confirm state and speak the read-back.
      if (result.needs_confirmation && result.pending_value != null) {
        pendingConfirm.current = {
          fieldKey: answeredKey,
          value: String(result.pending_value),
        };
        const msg = result.error || `I heard "${result.pending_value}" — is that right?`;
        setMessages(prev => [...prev, { id: uid(), role: "ai", text: msg, type: "clarification" }]);
        if (autoSpeak) speak(msg, () => { setTimeout(() => startListening(), 300); });
        return;
      }

      if (!result.success) {
        const msg = result.error || "Please try again.";
        setMessages(prev => [...prev, { id: uid(), role: "ai", text: msg, type: "clarification" }]);
        if (autoSpeak) speak(msg, (session.next_question?.is_sensitive && session.next_question?.field_type !== "date") ? undefined : () => {
          setTimeout(() => startListening(), 300);
        });
      } else {
        await handleSaveSuccess(result);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setShowTyping(false);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  /* Shared "answer accepted → acknowledge → next question" handling, used by
     both a normal save and a confirmed (smart-confirm "yes") save. */
  async function handleSaveSuccess(result: AnswerResult) {
    lastSpokenKey.current = null;
    const ack = result.acknowledgment?.trim();

    if (result.is_complete) {
      const done = `${ack ? ack + " " : ""}Great job! I've got everything I need. Taking you to review your answers now.`;
      setMessages(prev => [...prev, { id: uid(), role: "ai", text: done, type: "complete" }]);
      if (autoSpeak) speak(done);
      try { localStorage.removeItem(storageKey(sessionId)); } catch { /* ignore */ }
      refreshReview();
      setTimeout(() => router.push(`/review/${sessionId}`), autoSpeak ? 2200 : 700);
      return;
    }

    const nextQ = result.next_question;
    if (nextQ) {
      const q = nextQ.question;
      const spoken = ack ? `${ack} ${q}` : q;
      lastSpokenKey.current = nextQ.field_key;

      // Start TTS fetch immediately — before anything else
      if (autoSpeak) prefetchTts(spoken);

      if (ack) {
        setMessages(prev => [...prev, { id: uid(), role: "ai", text: ack, type: "question" }]);
      }

      // Update session state in background — don't await it before speaking
      api.getSession(sessionId).then(updated => {
        setSession(updated);
        refreshReview();
      });

      if (autoSpeak) {
        const micAllowed = !nextQ.is_sensitive || nextQ.field_type === "date";
        speak(spoken,
          micAllowed ? () => { setTimeout(() => startListening(), 300); } : undefined,
          () => setMessages(prev => [...prev, { id: uid(), role: "ai", text: q, type: "question" }]),
        );
      } else {
        setMessages(prev => [...prev, { id: uid(), role: "ai", text: q, type: "question" }]);
      }
    } else {
      // No next question in result — fall back to fetching session
      refreshReview();
      const updated = await api.getSession(sessionId);
      setSession(updated);
    }
  }

  /* Resubmit a value the user just confirmed ("yes") so it saves directly. */
  async function submitConfirmed(value: string, viaVoice: boolean) {
    if (!session?.next_question) return;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      const result: AnswerResult = await api.submitAnswer(sessionId, {
        field_key: session.next_question.field_key,
        raw_answer: value,
        input_mode: viaVoice ? "voice" : "typed",
        confirmed: true,
      });
      if (result.success) {
        await handleSaveSuccess(result);
      } else {
        const msg = result.error || "Let's try that again.";
        setMessages(prev => [...prev, { id: uid(), role: "ai", text: msg, type: "clarification" }]);
        if (autoSpeak) speak(msg, () => setTimeout(() => startListening(), 300));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  // Keep the ref pointed at the latest processAnswer so voice auto-submit uses
  // current state.
  processAnswerRef.current = processAnswer;

  /* form submit wrapper */
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    processAnswer(answer);
  }

  /* go back to previous question */
  async function handleGoBack() {
    if (submitting) return;
    stopSpeaking();
    stopListening();
    lastSpokenKey.current = null;
    pendingConfirm.current = null;
    setSubmitting(true);
    try {
      const updated = await api.goBack(sessionId);
      setSession(updated);
      await refreshReview();
      // Remove the last user answer bubble and any AI messages after it
      setMessages(prev => {
        const lastUserIdx = [...prev].reverse().findIndex(m => m.role === "user" && m.type === "answer");
        if (lastUserIdx === -1) return prev;
        const cutIdx = prev.length - 1 - lastUserIdx;
        return prev.slice(0, cutIdx);
      });
      if (updated.next_question) {
        const q = updated.next_question.question;
        lastSpokenKey.current = updated.next_question.field_key;
        const showBubble = () => setMessages(prev => [...prev, { id: uid(), role: "ai", text: q, type: "question" }]);
        if (autoSpeak) {
          prefetchTts(q);
          const micAllowed = !updated.next_question.is_sensitive || updated.next_question.field_type === "date";
          speak(q, micAllowed ? () => { setTimeout(() => startListening(), 300); } : undefined, showBubble);
        } else {
          showBubble();
        }
      }
    } catch {
      setError("Failed to go back.");
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  /* skip */
  async function handleSkip() {
    if (!session?.next_question) return;
    stopSpeaking();
    setAnswer("");
    lastSpokenKey.current = null;
    setSubmitting(true);
    try {
      const result = await api.skipField(sessionId, {
        field_key: session.next_question.field_key,
        raw_answer: "skipped",
        input_mode: "typed",
      });
      if (result.is_complete) {
        const done = "All done! Taking you to review your answers.";
        setMessages(prev => [...prev, { id: uid(), role: "ai", text: done, type: "complete" }]);
        if (autoSpeak) speak(done);
        try { localStorage.removeItem(storageKey(sessionId)); } catch { /* ignore */ }
        setTimeout(() => router.push(`/review/${sessionId}`), autoSpeak ? 2200 : 700);
        return;
      }
      setShowTyping(true);
      const [updated] = await Promise.all([api.getSession(sessionId), refreshReview()]);
      setSession(updated);
      setShowTyping(false);
      if (updated.next_question) {
        const q = updated.next_question.question;
        lastSpokenKey.current = updated.next_question.field_key;
        const showBubble = () => setMessages(prev => [...prev, { id: uid(), role: "ai", text: q, type: "question" }]);
        if (autoSpeak) {
          prefetchTts(q);
          const micAllowed = !updated.next_question.is_sensitive || updated.next_question.field_type === "date";
          speak(q, micAllowed ? () => { setTimeout(() => startListening(), 300); } : undefined, showBubble);
        } else {
          showBubble();
        }
      }
    } catch {
      setError("Failed to skip.");
      setShowTyping(false);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  /* ── Inline edit of a previously-answered field ── */
  function startEdit(msg: Message) {
    stopSpeaking();
    stopListening();
    setEditingMsgId(msg.id);
    setEditText(msg.text);
  }

  function cancelEdit() {
    setEditingMsgId(null);
    setEditText("");
  }

  async function saveEdit(msg: Message, override?: string) {
    const newText = (override ?? editText).trim();
    if (!msg.fieldKey || !newText) { cancelEdit(); return; }
    try {
      const result = await api.submitAnswer(sessionId, {
        field_key: msg.fieldKey,
        raw_answer: newText,
        input_mode: "typed",
      });
      if (!result.success) {
        setError(result.error || "Couldn't update that answer.");
        return;
      }
      setMessages(prev => prev.map(m => m.id === editingMsgId ? { ...m, text: newText } : m));
      setSession(prev => prev ? { ...prev, answers: result.answers ?? prev.answers } : prev);
      cancelEdit();
      refreshReview();
    } catch {
      setError("Couldn't update that answer.");
    }
  }

  function toggleMic() {
    if (isListening) {
      stopListening();
    } else {
      stopSpeaking();
      setVoiceError(null);
      // Wait for speechSynthesis to fully stop before starting recognition
      setTimeout(() => startListening(), 300);
    }
  }

  const q        = session?.next_question;
  const progress = session && session.total_required > 0
    ? Math.round(((session.answered_count ?? 0) / session.total_required) * 100)
    : 0;

  /* ── Loading screen ── */
  if (loading) {
    return (
      <div className="fixed inset-0 flex items-center justify-center"
        style={{ background: "linear-gradient(160deg,#0f172a 0%,#1e293b 100%)" }}>
        <div className="flex flex-col items-center gap-5">
          <div className="relative" style={{ width: 80, height: 80 }}>
            <span className="pulse-ring" /><span className="pulse-ring" /><span className="pulse-ring" />
            <div className="ai-orb absolute inset-0 rounded-full z-10 flex items-center justify-center">
              <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            </div>
          </div>
          <p className="text-slate-400 text-sm animate-pulse">Starting your session…</p>
        </div>
      </div>
    );
  }

  /* ── iPad layout: top bar + middle two-col + bottom AI panel ── */
  const filledCount = review?.sections
    ? Object.values(review.sections).flat().filter((f) => f.value !== null && f.value !== undefined && f.source !== "skipped").length
    : 0;
  const totalCount = review?.sections ? Object.values(review.sections).flat().length : 0;

  return (
    <div className="fixed inset-0 flex flex-col" style={{ background: "#0a0f1e" }}>

      {/* ══ TOP BAR — AI Form Assistant branding ══ */}
      <div
        className="shrink-0 flex items-center justify-between px-5 py-3 border-b border-white/5"
        style={{ background: "rgba(10,15,30,0.95)", backdropFilter: "blur(12px)" }}
      >
        <div className="flex items-center gap-3">
          <div className="ai-orb w-10 h-10 rounded-full flex items-center justify-center shrink-0">
            <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <div>
            <p className="text-base font-bold text-white leading-tight">AI Form Assistant</p>
            <p className="text-xs text-slate-500 leading-tight truncate max-w-[220px]">
              {session?.form_title ?? session?.form_id ?? "Form"}
            </p>
          </div>
        </div>
        <button className="w-9 h-9 rounded-full flex items-center justify-center border border-white/10 text-slate-400 hover:text-white hover:border-white/20 transition-all">
          <svg width="16" height="16" fill="currentColor" viewBox="0 0 24 24">
            <circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" />
          </svg>
        </button>
      </div>

      {/* ══ MIDDLE — Conversation (left) + Form Fields (right) ══ */}
      <div className="flex-1 flex min-h-0 gap-0">

        {/* ── Conversation column ── */}
        <div
          className="flex-1 flex flex-col min-w-0 border-r border-white/5"
          style={{ background: "linear-gradient(160deg,#0d1424 0%,#111827 100%)" }}
        >
          {/* Column header */}
          <div className="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-white/5">
            <div className="h-2 w-2 rounded-full bg-indigo-500 animate-pulse" />
            <span className="text-sm font-semibold text-white">Conversation</span>
            <span className="ml-auto text-[11px] text-slate-600 tabular-nums">Session {sessionId.slice(0, 8)}…</span>
          </div>

          {/* Chat messages */}
          <div className="flex-1 overflow-y-auto chat-area px-4 py-4">
            <div className="space-y-4">
              {messages.length === 0 && (
                <div className="flex items-end gap-2.5 anim-fade-up">
                  <MiniOrb size={28} />
                  <div className="bubble-ai">
                    <span className="text-slate-500 text-sm italic">Loading your first question…</span>
                  </div>
                </div>
              )}

              {messages.map((msg) => {
                if (msg.role === "ai") {
                  const isCurrent = q && msg.text === q.question && msg.type === "question";
                  const bubbleClass = msg.type === "clarification" ? "bubble-warn" : "bubble-ai";
                  return (
                    <div key={msg.id} className="flex items-end gap-2.5">
                      <MiniOrb size={28} />
                      <div className={bubbleClass}>
                        {isCurrent && q && (
                          <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                            <span className="text-[10px] font-bold tracking-widest uppercase text-indigo-400">
                              {q.field.section.replace(/_/g, " ")}
                            </span>
                            {q.is_optional && <span className="text-[9px] bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded-full">Optional</span>}
                            {q.is_sensitive && <span className="text-[9px] bg-red-900/50 text-red-400 px-1.5 py-0.5 rounded-full">Sensitive</span>}
                          </div>
                        )}
                        <p className="text-sm leading-relaxed">{msg.text}</p>
                        {isCurrent && voiceSupported && (
                          <button onClick={() => speak(msg.text)}
                            className="mt-2 flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
                            <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
                            </svg>
                            Replay
                          </button>
                        )}
                      </div>
                    </div>
                  );
                }
                const editable = msg.type === "answer" && !!msg.fieldKey && !msg.isSensitive;
                if (editingMsgId === msg.id) {
                  const isBool = msg.fieldType === "boolean";
                  return (
                    <div key={msg.id} className="flex justify-end">
                      {isBool ? (
                        <div className="flex items-center gap-2">
                          {["yes", "no"].map(opt => (
                            <button key={opt} onClick={() => saveEdit(msg, opt)}
                              className={`px-4 py-2 rounded-xl text-sm font-semibold border transition-all ${msg.text.toLowerCase() === opt ? "bg-indigo-600 border-indigo-500 text-white" : "border-slate-600 text-slate-300 hover:border-indigo-500"}`}>
                              {opt === "yes" ? "Yes" : "No"}
                            </button>
                          ))}
                          <button onClick={cancelEdit} className="p-1.5 rounded-lg text-slate-400 hover:text-white">
                            <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                          </button>
                        </div>
                      ) : (
                        <div className="bubble-user !bg-slate-800 flex items-center gap-1.5 py-1.5 pr-1.5 pl-3">
                          <input autoFocus type="text" value={editText} placeholder={msg.fieldType === "date" ? "e.g. 01/15/1985" : ""}
                            onChange={e => setEditText(e.target.value)}
                            onKeyDown={e => { if (e.key === "Enter") saveEdit(msg); if (e.key === "Escape") cancelEdit(); }}
                            className="bg-transparent outline-none text-white text-sm w-36" />
                          <button onClick={() => saveEdit(msg)} className="p-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white">
                            <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
                          </button>
                          <button onClick={cancelEdit} className="p-1.5 rounded-lg text-slate-400 hover:text-white">
                            <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                          </button>
                        </div>
                      )}
                    </div>
                  );
                }
                return (
                  <div key={msg.id} className="flex justify-end items-center gap-1.5 group">
                    {editable && (
                      <button onClick={() => startEdit(msg)} title="Edit"
                        className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg text-slate-500 hover:text-indigo-300 hover:bg-slate-800">
                        <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zM19.5 7.125L16.875 4.5" />
                        </svg>
                      </button>
                    )}
                    <div className="bubble-user text-sm">{msg.text}</div>
                  </div>
                );
              })}

              {showTyping && <TypingIndicator />}

              {(error || voiceError) && (
                <div className="flex justify-center anim-fade-up">
                  <div className="text-xs text-red-300 bg-red-900/25 border border-red-700/30 rounded-xl px-4 py-2.5 text-center max-w-xs">
                    {error || voiceError}
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          {/* Input bar */}
          {q && (
            <div className="shrink-0 px-4 py-3 border-t border-white/5"
              style={{ background: "rgba(10,15,30,0.9)", backdropFilter: "blur(12px)" }}>
              <form onSubmit={handleSubmit}>
                {q.field_type === "boolean" ? (
                  <div className="flex items-center gap-3">
                    <button type="button" onClick={handleGoBack} disabled={submitting || (session?.answered_count ?? 0) === 0}
                      title="Go back to previous question"
                      className="shrink-0 h-12 w-12 rounded-2xl flex items-center justify-center text-slate-500 border border-slate-700 hover:text-slate-300 hover:border-slate-600 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                      <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
                      </svg>
                    </button>
                    {["Yes", "No"].map(opt => (
                      <button key={opt} type="button" onClick={() => processAnswer(opt.toLowerCase())} disabled={submitting}
                        className="flex-1 py-3.5 rounded-2xl text-base font-semibold transition-all border border-slate-700 text-slate-300 hover:border-indigo-500 hover:text-white disabled:opacity-40">
                        {opt}
                      </button>
                    ))}
                    {q.is_optional && (
                      <button type="button" onClick={handleSkip} disabled={submitting}
                        className="shrink-0 h-12 px-5 rounded-2xl text-sm font-medium text-slate-500 border border-slate-700 hover:text-slate-300 transition-all disabled:opacity-40">
                        Skip
                      </button>
                    )}
                  </div>
                ) : q.field_type === "select" && Array.isArray((q.field.validation_rule as Record<string, unknown>)?.allowed_values) ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    <button type="button" onClick={handleGoBack} disabled={submitting || (session?.answered_count ?? 0) === 0}
                      title="Go back to previous question"
                      className="shrink-0 h-11 w-11 rounded-2xl flex items-center justify-center text-slate-500 border border-slate-700 hover:text-slate-300 hover:border-slate-600 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                      <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
                      </svg>
                    </button>
                    {((q.field.validation_rule as Record<string, unknown>).allowed_values as string[]).map(val => (
                      <button key={val} type="button" onClick={() => processAnswer(val)} disabled={submitting}
                        className="flex-1 min-w-fit py-3.5 px-4 rounded-2xl text-sm font-semibold transition-all border border-slate-700 text-slate-300 hover:border-indigo-500 hover:text-white disabled:opacity-40 capitalize whitespace-nowrap">
                        {val.replace(/_/g, " ")}
                      </button>
                    ))}
                    {q.is_optional && (
                      <button type="button" onClick={handleSkip} disabled={submitting}
                        className="shrink-0 h-11 px-4 rounded-2xl text-sm font-medium text-slate-500 border border-slate-700 hover:text-slate-300 transition-all disabled:opacity-40">
                        Skip
                      </button>
                    )}
                  </div>
                ) : (q.is_sensitive || showTypeBox) ? (
                  <div className="flex items-center gap-2.5">
                    <button type="button" onClick={handleGoBack} disabled={submitting || (session?.answered_count ?? 0) === 0}
                      title="Go back to previous question"
                      className="shrink-0 h-12 w-12 rounded-2xl flex items-center justify-center text-slate-500 border border-slate-700 hover:text-slate-300 hover:border-slate-600 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                      <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
                      </svg>
                    </button>
                    <input ref={inputRef} autoFocus
                      type={q.is_sensitive && q.field_type !== "date" ? "password" : "text"}
                      value={answer} onChange={e => setAnswer(e.target.value)}
                      placeholder={q.field_type === "date" ? "e.g. 01/15/1985" : q.is_sensitive ? "Type your answer (voice disabled)" : "Type your answer…"}
                      className="flex-1 rounded-2xl px-5 py-3.5 text-base outline-none bg-slate-800/80 border border-slate-700 text-white placeholder-slate-600 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30 transition-all" />
                    {!q.is_sensitive && (
                      <button type="button" onClick={() => { setShowTypeBox(false); setAnswer(""); }}
                        className="shrink-0 h-12 w-12 rounded-2xl flex items-center justify-center text-slate-400 border border-slate-700 hover:text-white transition-all">
                        <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
                        </svg>
                      </button>
                    )}
                    {q.is_optional && (
                      <button type="button" onClick={handleSkip} disabled={submitting}
                        className="shrink-0 h-12 px-5 rounded-2xl text-sm font-medium text-slate-500 border border-slate-700 hover:text-slate-300 transition-all disabled:opacity-40">
                        Skip
                      </button>
                    )}
                    <button type="submit" disabled={submitting || !answer.trim()}
                      className="shrink-0 h-12 px-6 rounded-2xl text-base font-semibold flex items-center justify-center gap-2 transition-all"
                      style={{ background: submitting || !answer.trim() ? "rgba(30,41,59,0.8)" : "linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%)", color: submitting || !answer.trim() ? "#475569" : "white" }}>
                      {submitting ? "Saving…" : "Send"}
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center justify-center gap-5">
                    <button type="button" onClick={handleGoBack} disabled={submitting || (session?.answered_count ?? 0) === 0}
                      title="Go back to previous question"
                      className="shrink-0 h-9 w-9 rounded-full flex items-center justify-center text-slate-600 border border-slate-800 hover:text-slate-400 hover:border-slate-700 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                      <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
                      </svg>
                    </button>
                    <span className="text-sm text-slate-500">
                      {isListening ? "Listening — speak your answer" : "Tap the mic and speak your answer"}
                    </span>
                    <button type="button" onClick={() => { stopListening(); setShowTypeBox(true); }}
                      className="text-sm font-semibold text-indigo-400 hover:text-indigo-300 transition-colors">
                      Type instead
                    </button>
                    {q.is_optional && (
                      <button type="button" onClick={handleSkip} disabled={submitting}
                        className="text-sm text-slate-500 hover:text-slate-300 transition-colors disabled:opacity-40">
                        Skip
                      </button>
                    )}
                  </div>
                )}
              </form>
            </div>
          )}

          {/* All done */}
          {!q && !loading && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center anim-fade-up px-6">
                <div className="relative mx-auto mb-6" style={{ width: 72, height: 72 }}>
                  <div className="absolute inset-0 rounded-full"
                    style={{ background: "linear-gradient(135deg,#10b981,#059669)", boxShadow: "0 0 28px 6px rgba(16,185,129,0.3)" }} />
                  <div className="relative z-10 h-full w-full flex items-center justify-center">
                    <svg width="30" height="30" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                  </div>
                </div>
                <h2 className="text-lg font-bold text-white mb-1.5">All done!</h2>
                <p className="text-slate-400 text-sm mb-5">Ready to review and download your PDF.</p>
                <button onClick={() => router.push(`/review/${sessionId}`)}
                  className="px-7 py-3 rounded-2xl text-base font-semibold text-white"
                  style={{ background: "linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%)" }}>
                  Go to Review →
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ── Form Fields column ── */}
        <div className="shrink-0 flex flex-col" style={{ width: 380, background: "rgba(8,12,24,0.8)" }}>
          <div className="shrink-0 px-4 py-2.5 border-b border-white/5 flex items-center justify-between"
            style={{ background: "rgba(10,15,30,0.95)" }}>
            <span className="text-xs font-bold tracking-widest uppercase text-slate-300">Form Fields</span>
            <span className="text-xs text-slate-500 tabular-nums">{filledCount} / {totalCount} filled</span>
          </div>
          <FieldsPanel review={review} currentFieldKey={q?.field_key} />
        </div>

      </div>

      {/* ══ BOTTOM PANEL — orb + status + waveform + progress ══ */}
      <div
        className="shrink-0 border-t border-white/5"
        style={{ background: "linear-gradient(180deg,#0c1120 0%,#0a0f1e 100%)", height: 188 }}
      >
        <div className="grid h-full items-center px-4 gap-3" style={{ gridTemplateColumns: "auto 1fr auto" }}>

          {/* ── ZONE 1 (left): orb + status + mic/voice controls ── */}
          <div className="flex items-center gap-3">
            {/* orb */}
            <div className="shrink-0 relative" style={{ width: 56, height: 56 }}>
              {orbMode === "speaking" && (<><span className="pulse-ring" /><span className="pulse-ring" /></>)}
              <div className="ai-orb absolute inset-0 rounded-full z-10 flex items-center justify-center">
                {orbMode === "listening" ? (
                  <div className="flex items-end gap-[3px]" style={{ height: 22 }}>
                    {[6, 12, 18, 12, 6].map((h, i) => <span key={i} className="wave-bar" style={{ height: h }} />)}
                  </div>
                ) : (
                  <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="white" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                  </svg>
                )}
              </div>
            </div>

            {/* status + controls stacked */}
            <div className="flex flex-col gap-2">
              <div className="flex flex-col gap-0.5">
                <span className="text-lg font-bold text-white leading-none">
                  {isSpeaking ? "Speaking…" : isListening ? "Listening…" : isProcessing ? "Processing…" : "Ready"}
                </span>
                <div className="flex items-center gap-1.5">
                  <div className="h-1.5 w-1.5 rounded-full shrink-0" style={{
                    background: isSpeaking ? "#818cf8" : isListening ? "#fb7185" : isProcessing ? "#f59e0b" : "#64748b",
                  }} />
                  <span className="text-xs text-slate-400 whitespace-nowrap">
                    {isSpeaking ? "Listen to the question" : isListening ? "Speak now" : isProcessing ? "Transcribing your answer…" : "Waiting for your answer"}
                  </span>
                </div>
              </div>

              {/* mic + voice controls */}
              {voiceSupported && (
                <div className="flex items-center gap-2">
                  {/* Mic button — disabled while speaking or processing, or for sensitive non-date fields */}
                  <button
                    onClick={toggleMic}
                    disabled={isSpeaking || isProcessing || submitting || ((q?.is_sensitive ?? false) && q?.field_type !== "date")}
                    title={isListening ? "Stop listening" : "Start listening"}
                    className={`flex items-center justify-center w-10 h-10 rounded-full transition-all ${
                      isListening
                        ? "bg-red-500 text-white shadow-lg shadow-red-900/60 hover:bg-red-600"
                        : (isSpeaking || isProcessing || submitting || ((q?.is_sensitive ?? false) && q?.field_type !== "date"))
                          ? "bg-slate-800/60 text-slate-700 border border-slate-800 cursor-not-allowed"
                          : "bg-slate-800/80 text-slate-300 border border-slate-700 hover:border-indigo-500 hover:text-indigo-400"
                    }`}>
                    {isListening
                      ? <svg width="16" height="16" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
                      : <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" /></svg>
                    }
                  </button>

                  {/* Stop button — appears when speaking or processing (lets user interrupt) */}
                  {(isSpeaking || isProcessing) && (
                    <button
                      onClick={() => { stopSpeaking(); stopListening(); }}
                      title="Stop"
                      className="flex items-center justify-center w-10 h-10 rounded-full bg-slate-800/80 border border-red-800/60 text-red-400 hover:bg-red-900/30 hover:border-red-500 transition-all">
                      <svg width="14" height="14" fill="currentColor" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="2" /></svg>
                    </button>
                  )}

                  <button onClick={() => { setAutoSpeak(v => { if (v) { stopSpeaking(); stopListening(); } return !v; }); }}
                    className={`flex items-center gap-1.5 px-3 h-10 rounded-full text-xs font-medium border transition-all ${
                      autoSpeak ? "bg-indigo-600/20 border-indigo-500/40 text-indigo-300 hover:bg-indigo-600/30"
                      : "bg-slate-800/60 border-slate-700 text-slate-500 hover:border-slate-600 hover:text-slate-300"
                    }`}>
                    <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
                    </svg>
                    {autoSpeak ? "Voice On" : "Voice Off"}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* ── ZONE 2 (center): waveform visualizer ── */}
          <div className="flex items-center justify-center h-full overflow-hidden px-2">
            {orbMode !== "idle" ? (
              <div className={`wave-viz ${orbMode} anim-fade-up w-full`}>
                {Array.from({ length: 24 }).map((_, i) => <div key={i} className="wave-viz-bar" />)}
              </div>
            ) : (
              <div className="flex items-center justify-center gap-[4px] w-full" style={{ height: 48 }}>
                {[10, 18, 28, 20, 38, 28, 46, 34, 24, 16, 30, 42, 36, 24, 14, 28, 40, 32, 18, 12, 26, 36, 22, 14].map((h, i) => (
                  <div key={i} style={{ flex: 1, maxWidth: 5, height: h, borderRadius: 9999, background: "rgba(99,102,241,0.18)" }} />
                ))}
              </div>
            )}
          </div>

          {/* ── ZONE 3 (right): progress + go to review ── */}
          <div className="flex flex-col gap-2.5" style={{ minWidth: 160, maxWidth: 200 }}>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-slate-400 whitespace-nowrap">Form progress</span>
                <span className="text-xs text-white tabular-nums font-semibold">{progress}%</span>
              </div>
              <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full rounded-full transition-all duration-700"
                  style={{ width: `${progress}%`, background: "linear-gradient(90deg,#6366f1,#8b5cf6)" }} />
              </div>
              <p className="text-xs text-slate-500 tabular-nums">{session?.missing_count ?? 0} fields remaining</p>
            </div>
            <button onClick={() => router.push(`/review/${sessionId}`)}
              className="flex items-center justify-center gap-1.5 py-2 rounded-xl border border-slate-700 text-xs font-medium text-slate-300 hover:text-white hover:border-indigo-500 hover:bg-indigo-600/10 transition-all whitespace-nowrap">
              Go to review
              <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
              </svg>
            </button>
          </div>

        </div>
      </div>

    </div>
  );
}
