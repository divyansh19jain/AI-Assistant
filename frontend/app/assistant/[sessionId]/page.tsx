"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, type NextField } from "@/lib/api";
import { useVoice } from "@/lib/useVoice";
import type { SessionState, ReviewResponse, ReviewField } from "@/lib/types";

/* ── Conversation model ─────────────────────────────────────────────── */
interface Msg { id: string; role: "assistant" | "user"; text: string; }
let _id = Date.now();
const uid = () => String(++_id);
const msgKey = (sid: string) => `agent_chat_${sid}`;
const nfKey = (sid: string) => `agent_nextfield_${sid}`;

/* ── Brand orb avatar ───────────────────────────────────────────────── */
function Orb({ size = 36 }: { size?: number }) {
  return (
    <div className="orb-clinical shrink-0 flex items-center justify-center rounded-full"
      style={{ width: size, height: size }}>
      <svg style={{ width: size * 0.5, height: size * 0.5 }} viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round"
          d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
      </svg>
    </div>
  );
}

function TypingDots() {
  return (
    <div className="flex items-end gap-2.5">
      <Orb size={32} />
      <div className="bubble-ai flex items-center gap-1.5 py-3.5">
        <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
      </div>
    </div>
  );
}

/* ── Voice status pill ──────────────────────────────────────────────── */
function StatusPill({ mode }: { mode: "idle" | "listening" | "speaking" | "thinking" }) {
  const map = {
    idle:      { label: "Ready",      color: "#64748b", bg: "#f1f5f9", border: "#e2e8f0" },
    listening: { label: "Listening…", color: "#dc2626", bg: "#fef2f2", border: "#fecaca" },
    speaking:  { label: "Speaking…",  color: "#2563eb", bg: "#eff6ff", border: "#bfdbfe" },
    thinking:  { label: "Thinking…",  color: "#7c3aed", bg: "#f5f3ff", border: "#ddd6fe" },
  }[mode];
  return (
    <div className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition-colors"
      style={{ color: map.color, background: map.bg, border: `1px solid ${map.border}` }}>
      {mode === "idle" ? (
        <span className="h-2 w-2 rounded-full" style={{ background: map.color }} />
      ) : (
        <span className="flex items-end gap-[2px] h-3.5"><i className="eq-bar" /><i className="eq-bar" /><i className="eq-bar" /><i className="eq-bar" /><i className="eq-bar" /></span>
      )}
      {map.label}
    </div>
  );
}

/* ── "Your information" sidebar ─────────────────────────────────────── */
function InfoPanel({ review, currentKey }: { review: ReviewResponse | null; currentKey: string | null }) {
  if (!review) {
    return <div className="flex items-center justify-center h-full text-sm text-slate-400">Loading…</div>;
  }
  return (
    <div className="flex flex-col h-full overflow-y-auto chat-area">
      {Object.entries(review.sections).map(([sectionKey, fields]) => {
        const filled = fields.filter((f) => f.value !== null && f.value !== undefined && f.source !== "skipped").length;
        return (
          <div key={sectionKey} className="mb-1">
            <div className="sticky top-0 z-10 px-4 py-2.5 flex items-center justify-between bg-slate-50/95 backdrop-blur border-b border-slate-200">
              <span className="text-xs font-bold tracking-wider uppercase text-slate-500">{sectionKey.replace(/_/g, " ")}</span>
              <span className="text-xs text-slate-400 tabular-nums">{filled}/{fields.length}</span>
            </div>
            <div className="divide-y divide-slate-100">
              {fields.map((field: ReviewField) => {
                const isSkipped = field.source === "skipped";
                const isMissing = field.value === null || field.value === undefined;
                const isCurrent = field.field_key === currentKey;
                const display = field.is_sensitive && !isMissing && !isSkipped ? "••••••"
                  : isSkipped ? "Skipped" : isMissing ? "—" : String(field.value);
                return (
                  <div key={field.field_key} className="px-4 py-2.5 transition-colors"
                    style={{ background: isCurrent ? "#eff6ff" : "transparent", borderLeft: isCurrent ? "3px solid #2563eb" : "3px solid transparent" }}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] text-slate-500 truncate flex-1">
                        {field.label}{!field.is_required && <span className="ml-1 text-[11px] text-slate-400">(optional)</span>}
                      </span>
                      {isCurrent ? <Badge tone="blue">Now</Badge>
                        : !isMissing && !isSkipped ? <Badge tone="green">✓</Badge>
                        : isSkipped ? <Badge tone="slate">Skipped</Badge>
                        : field.is_required ? <Badge tone="amber">Needed</Badge> : null}
                    </div>
                    <p className={`mt-0.5 text-sm font-medium truncate ${isMissing && !isSkipped ? "text-slate-300" : isSkipped ? "text-slate-400 italic" : "text-slate-800"}`}>{display}</p>
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

function Badge({ tone, children }: { tone: "blue" | "green" | "amber" | "slate"; children: React.ReactNode }) {
  const tones = {
    blue:  "bg-blue-100 text-blue-700",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100 text-amber-700",
    slate: "bg-slate-100 text-slate-500",
  }[tone];
  return <span className={`shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-md ${tones}`}>{children}</span>;
}

/* ── Page ───────────────────────────────────────────────────────────── */
export default function AssistantPage() {
  const router = useRouter();
  const { sessionId } = useParams() as { sessionId: string };

  const [session, setSession]   = useState<SessionState | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [review, setReview]     = useState<ReviewResponse | null>(null);
  const [input, setInput]       = useState("");
  const [thinking, setThinking] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [nextKey, setNextKey]   = useState<string | null>(null);
  const [nextField, setNextField] = useState<NextField | null>(null);
  const [loading, setLoading]   = useState(true);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLInputElement>(null);
  // The field currently being asked — sent with the answer so the backend binds it to the
  // right field deterministically (no text-guessing). Ref avoids stale closures in voice.
  const nextFieldRef = useRef<NextField | null>(null);
  const started   = useRef(false);
  const sendRef   = useRef<(t: string, mode: string) => void>(() => {});
  const doneRef   = useRef(false);
  const thinkingRef = useRef(false);

  // Build a Whisper hint from the field we're currently expecting.
  const currentLabel = nextKey && review
    ? Object.values(review.sections).flat().find((f) => f.field_key === nextKey)?.label ?? ""
    : "";

  const rearmRef = useRef<() => void>(() => {});
  const noSpeechCount = useRef(0);

  const {
    status: voiceStatus, supported: voiceSupported,
    speak, stopSpeaking, startListening, stopListening, clearTranscript, unlockAudio,
  } = useVoice({
    formId: session?.form_id,
    hint: currentLabel ? `${currentLabel}, skip, yes, no` : "skip, yes, no",
    onTranscript: (t) => {
      const clean = t.trim();
      noSpeechCount.current = 0;
      setInput(clean);
      setVoiceError(null);
      setTimeout(() => sendRef.current(clean, "voice"), 250);
    },
    onError: (m) => setVoiceError(m),
    onNoSpeech: () => rearmRef.current(),
  });
  const voiceStatusRef = useRef(voiceStatus);
  useEffect(() => { voiceStatusRef.current = voiceStatus; }, [voiceStatus]);

  // Hands-free re-arm: if a listen captured nothing (silence/echo), try again a
  // couple of times, then fall back to idle so the composer is clearly usable —
  // the conversation never dead-ends on a missed capture.
  rearmRef.current = () => {
    if (doneRef.current || thinkingRef.current) return;
    if (voiceStatusRef.current === "speaking") return;
    if (noSpeechCount.current < 2) {
      noSpeechCount.current += 1;
      setTimeout(() => startListening(), 400);
    } else {
      noSpeechCount.current = 0;
      inputRef.current?.focus(); // give up gracefully — make the composer the obvious next step
    }
  };

  const isListening = voiceStatus === "listening";
  const isSpeaking  = voiceStatus === "speaking";
  const isProcessing = voiceStatus === "processing";
  const mode: "idle" | "listening" | "speaking" | "thinking" =
    isListening ? "listening" : isSpeaking ? "speaking" : (thinking || isProcessing) ? "thinking" : "idle";

  const pushMsg = useCallback((role: "assistant" | "user", text: string) => {
    setMessages((prev) => {
      const next = [...prev, { id: uid(), role, text }];
      // sessionStorage (not localStorage): the chat is client-side PHI and must not
      // survive a closed tab/browser on a shared or kiosk device.
      try { sessionStorage.setItem(msgKey(sessionId), JSON.stringify(next)); } catch { /* quota */ }
      return next;
    });
  }, [sessionId]);

  const refreshReview = useCallback(async () => {
    try { setReview(await api.getReview(sessionId)); } catch { /* keep stale */ }
  }, [sessionId]);

  // Speak a reply, then (hands-free) reopen the mic when it's the user's turn.
  const speakReply = useCallback((text: string, canListen: boolean) => {
    if (!autoSpeak) return;
    speak(text, canListen ? () => setTimeout(() => startListening(), 350) : undefined);
  }, [autoSpeak, speak, startListening]);

  // Core: one agent turn.
  const sendToAgent = useCallback(async (text: string, inputMode: string) => {
    const clean = text.trim();
    if (!clean || doneRef.current) return;
    if (thinkingRef.current) {
      setInput(clean);
      setVoiceError("I heard that. Please wait for Mia's next question before answering again.");
      return;
    }
    stopSpeaking(); stopListening(); clearTranscript();
    setVoiceError(null);
    noSpeechCount.current = 0;
    pushMsg("user", clean);
    setInput("");
    thinkingRef.current = true;
    setThinking(true);
    try {
      const r = await api.agent(sessionId, clean, inputMode, nextFieldRef.current?.field_key ?? null);
      pushMsg("assistant", r.assistant_message);
      setProgress(r.state.total ? Math.round(((r.state.total - r.state.missing_count) / r.state.total) * 100) : 0);
      setNextKey(r.state.next_field_key);
      const nf = r.done ? null : (r.next_field ?? null);
      nextFieldRef.current = nf;
      setNextField(nf);
      refreshReview();
      if (r.done) {
        doneRef.current = true;
        if (autoSpeak) speak(r.assistant_message);
        // Clear the client-side PHI transcript the moment we're done with it.
        try { sessionStorage.removeItem(msgKey(sessionId)); } catch { /* ignore */ }
        setTimeout(() => router.push(`/review/${sessionId}`), autoSpeak ? 2600 : 900);
      } else {
        speakReply(r.assistant_message, true);
      }
    } catch {
      const errorMessage = "Something went wrong reaching the assistant. Please try again.";
      setVoiceError(errorMessage);
      if (autoSpeak) {
        speak(errorMessage, () => setTimeout(() => startListening(), 500));
      } else {
        inputRef.current?.focus();
      }
    } finally {
      thinkingRef.current = false;
      setThinking(false);
    }
  }, [sessionId, autoSpeak, pushMsg, refreshReview, speak, speakReply, startListening, stopSpeaking, stopListening, clearTranscript, router]);
  sendRef.current = sendToAgent;

  /* Load session + kick off the conversation. */
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const [s] = await Promise.all([api.getSession(sessionId), refreshReview()]);
        setSession(s);
        setProgress(s.total_required ? Math.round(((s.answered_count ?? 0) / s.total_required) * 100) : 0);
        // Restore visible chat on reload; otherwise greet via the agent.
        let restored: Msg[] | null = null;
        try { const raw = sessionStorage.getItem(msgKey(sessionId)); restored = raw ? JSON.parse(raw) : null; } catch { /* ignore */ }
        setLoading(false);
        if (restored && restored.length) {
          setMessages(restored);
          // Restore the field binding too, so the next answer still goes to the right field.
          try {
            const rawNf = sessionStorage.getItem(nfKey(sessionId));
            if (rawNf) {
              const nf = JSON.parse(rawNf);
              nextFieldRef.current = nf;
              setNextField(nf);
              setNextKey(nf?.field_key ?? null);
            }
          } catch { /* ignore */ }
          setTimeout(() => startListening(), 400);
        } else {
          // try/finally so a slow/failed greeting can never leave `thinking` stuck
          // (which would disable the mic, Send, and sending — a hard dead-end).
          try {
            thinkingRef.current = true;
            setThinking(true);
            const r = await api.agent(sessionId, "__start__", "voice");
            pushMsg("assistant", r.assistant_message);
            setNextKey(r.state.next_field_key);
            nextFieldRef.current = r.next_field ?? null;
            setNextField(r.next_field ?? null);
            refreshReview();
            speakReply(r.assistant_message, true);
          } catch {
            const errorMessage = "Couldn't start the assistant - type your answer or tap the mic to begin.";
            setVoiceError(errorMessage);
            if (autoSpeak) {
              speakReply(errorMessage, true);
            } else {
              inputRef.current?.focus();
            }
          } finally {
            thinkingRef.current = false;
            setThinking(false);
          }
        }
      } catch {
        setLoading(false);
        setVoiceError("Couldn't load this session.");
      }
    })();
  }, [sessionId, autoSpeak, refreshReview, pushMsg, speakReply, startListening]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, thinking]);
  // Persist the current field binding so a reload keeps answers bound to the right field.
  useEffect(() => {
    try {
      if (nextField) sessionStorage.setItem(nfKey(sessionId), JSON.stringify(nextField));
      else sessionStorage.removeItem(nfKey(sessionId));
    } catch { /* quota */ }
  }, [nextField, sessionId]);
  useEffect(() => { if (mode === "idle") inputRef.current?.focus(); }, [mode]);
  useEffect(() => { if (!voiceError) return; const t = setTimeout(() => setVoiceError(null), 5000); return () => clearTimeout(t); }, [voiceError]);

  // Unlock audio on the first user gesture so first-load TTS isn't blocked by the
  // browser autoplay policy (a suspended AudioContext plays nothing and never ends).
  useEffect(() => {
    const unlock = () => unlockAudio();
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return () => { window.removeEventListener("pointerdown", unlock); window.removeEventListener("keydown", unlock); };
  }, [unlockAudio]);

  function toggleMic() {
    if (isListening) { stopListening(); }
    else { stopSpeaking(); setVoiceError(null); setTimeout(() => startListening(), 250); }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center gap-4">
          <Orb size={64} />
          <p className="text-slate-500 text-sm">Getting things ready…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell flex flex-col w-full overflow-hidden bg-slate-50 text-slate-800">
      {/* Header */}
      <header className="shrink-0 bg-white border-b border-slate-200 pt-[env(safe-area-inset-top)]">
        <div className="flex items-center gap-2 sm:gap-3 px-3 sm:px-5 h-16">
          <Orb size={40} />
          <div className="min-w-0">
            <p className="font-bold leading-tight truncate">{session?.form_title ?? "Application Assistant"}</p>
            <p className="text-xs text-slate-400 leading-tight">Mia · your form helper</p>
          </div>
          {session?.mock_mode && (
            <span className="ml-1 text-[11px] font-semibold bg-amber-50 text-amber-600 border border-amber-200 px-2 py-0.5 rounded-full">DEMO</span>
          )}
          <div className="ml-auto flex items-center gap-2 sm:gap-4">
            <div className="flex items-center gap-2.5 w-20 sm:w-56">
              <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                <div className="h-full rounded-full transition-all duration-700" style={{ width: `${progress}%`, background: "linear-gradient(90deg,#3b82f6,#2563eb)" }} />
              </div>
              <span className="text-sm font-semibold text-slate-500 tabular-nums w-9 text-right">{progress}%</span>
            </div>
            <button onClick={() => router.push(`/review/${sessionId}`)}
              className="md:hidden h-11 px-3 inline-flex items-center rounded-full text-sm font-medium border border-slate-200 text-slate-600 hover:bg-slate-50">
              Review
            </button>
            <button onClick={() => setAutoSpeak((v) => { if (v) { stopSpeaking(); stopListening(); } return !v; })}
              className={`flex items-center gap-2 px-3 sm:px-3.5 h-11 rounded-full text-sm font-medium border transition-colors ${autoSpeak ? "bg-blue-50 border-blue-200 text-blue-700 hover:bg-blue-100" : "bg-slate-50 border-slate-200 text-slate-500 hover:bg-slate-100"}`}>
              <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                {autoSpeak
                  ? <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
                  : <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />}
              </svg>
              <span className="hidden sm:inline">{autoSpeak ? "Voice on" : "Voice off"}</span>
            </button>
          </div>
        </div>
      </header>

      {/* Body */}
      <div className="flex-1 flex min-h-0">
        {/* Conversation */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 overflow-y-auto chat-area px-4 sm:px-5 py-6">
            <div className="max-w-3xl mx-auto space-y-4">
              {messages.map((m) => m.role === "assistant" ? (
                <div key={m.id} className="flex items-end gap-2.5 anim-fade-up">
                  <Orb size={32} />
                  <div className="bubble-ai">{m.text}</div>
                </div>
              ) : (
                <div key={m.id} className="flex justify-end anim-fade-up"><div className="bubble-user">{m.text}</div></div>
              ))}
              {thinking && <TypingDots />}
              <div ref={bottomRef} />
            </div>
          </div>

          {/* Toast */}
          {voiceError && (
            <div className="shrink-0 px-5">
              <div className="max-w-3xl mx-auto"><div className="toast toast-error mb-2">
                <svg width="16" height="16" className="shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" /></svg>
                <span className="flex-1">{voiceError}</span>
                <button onClick={() => setVoiceError(null)} className="toast-dismiss"><svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg></button>
              </div></div>
            </div>
          )}

          {/* Composer */}
          <div className="shrink-0 bg-white border-t border-slate-200 px-4 sm:px-5 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <div className="max-w-3xl mx-auto">
              <div className="flex items-center justify-between mb-2.5">
                <StatusPill mode={mode} />
                <button onClick={() => sendToAgent("skip", "typed")} disabled={thinking || doneRef.current}
                  className="min-h-[44px] -my-1 px-2 inline-flex items-center text-sm font-medium text-slate-500 hover:text-slate-700 disabled:opacity-40">Skip this question</button>
              </div>

              {/* Tappable answer chips — fast touch entry on a phone/tablet when voice is
                  unclear. Yes/No for booleans, options for selects, common values otherwise.
                  Centered + finger-sized for visibility. */}
              {nextField && nextField.suggestions.length > 0 && !doneRef.current && (
                <div className="mb-3">
                  <p className="text-center text-xs text-slate-400 mb-2">Tap an answer, or type / speak it</p>
                  <div className="flex flex-wrap justify-center gap-2.5">
                    {nextField.suggestions.map((s) => (
                      <button key={s} type="button" disabled={thinking}
                        onClick={() => sendToAgent(s, "typed")}
                        className="min-h-[48px] inline-flex items-center px-5 py-3 rounded-full border-2 border-slate-200 bg-white text-base font-semibold text-slate-700 shadow-sm hover:border-blue-400 hover:bg-blue-50 hover:text-blue-700 active:scale-95 transition-all disabled:opacity-40">
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <form onSubmit={(e) => { e.preventDefault(); sendToAgent(input, "typed"); }} className="flex items-center gap-2.5">
                <div className="composer flex-1 flex items-center gap-1.5 rounded-2xl bg-slate-50 border border-slate-200 pl-4 pr-1.5 py-1.5">
                  <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} autoFocus
                    placeholder={isListening ? "Listening — speak your answer…" : "Type your answer, or tap the mic to speak"}
                    className="flex-1 bg-transparent outline-none text-[1.0625rem] text-slate-800 placeholder-slate-400 py-1.5" />
                  {/* Tapping while Mia is speaking interrupts her and starts listening
                      (barge-in) — toggleMic calls stopSpeaking() before startListening(). */}
                  {voiceSupported && (
                    <button type="button" onClick={toggleMic} disabled={isProcessing || thinking}
                      title={isListening ? "Stop listening" : isSpeaking ? "Tap to interrupt" : "Speak your answer"}
                      className={`shrink-0 flex items-center justify-center w-11 h-11 rounded-xl transition-all ${isListening ? "bg-red-500 text-white mic-live" : isSpeaking ? "text-blue-600 bg-blue-50 hover:bg-blue-100" : (isProcessing || thinking) ? "text-slate-300 cursor-not-allowed" : "text-slate-500 hover:text-blue-600 hover:bg-blue-50"}`}>
                      {isListening
                        ? <svg width="16" height="16" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2.5" /></svg>
                        : <svg width="17" height="17" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" /></svg>}
                    </button>
                  )}
                </div>
                <button type="submit" disabled={thinking || !input.trim()}
                  className="shrink-0 h-12 px-6 rounded-2xl text-base font-semibold text-white transition-all disabled:opacity-40"
                  style={{ background: thinking || !input.trim() ? "#94a3b8" : "linear-gradient(135deg,#2563eb,#1e40af)" }}>
                  Send
                </button>
              </form>
            </div>
          </div>
        </div>

        {/* Info sidebar — shown from iPad portrait (md) up; phones use the header Review link. */}
        <aside className="hidden md:flex flex-col w-72 md:w-80 xl:w-96 shrink-0 bg-slate-50 border-l border-slate-200">
          <div className="shrink-0 px-4 h-12 flex items-center justify-between border-b border-slate-200 bg-white">
            <span className="text-sm font-bold text-slate-700">Your information</span>
            <button onClick={() => router.push(`/review/${sessionId}`)}
              className="text-sm font-medium text-blue-600 hover:text-blue-700 flex items-center gap-1">
              Review <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" /></svg>
            </button>
          </div>
          <InfoPanel review={review} currentKey={nextKey} />
        </aside>
      </div>
    </div>
  );
}
