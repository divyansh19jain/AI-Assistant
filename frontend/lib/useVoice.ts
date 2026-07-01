"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export type VoiceStatus =
  | "idle"
  | "speaking"
  | "listening"
  | "processing"
  | "error"
  | "unsupported";

interface UseVoiceOptions {
  onTranscript?: (text: string) => void;
  onError?: (msg: string) => void;
  /** Fires when a listen attempt captured nothing usable (silence/echo/hallucination)
   *  so the caller can re-arm the mic instead of dead-ending the conversation. */
  onNoSpeech?: () => void;
  /** Passed to Whisper as a prompt hint — use the current field label + common values. */
  hint?: string;
  /** Selects the form's configured voice (TTS) + speech vocabulary (STT). */
  formId?: string;
}

const log = (...args: any[]) => console.log("[voice]", ...args);

const PREFERRED_FEMALE_VOICES = [
  "Microsoft Aria", "Microsoft Jenny", "Microsoft Michelle",
  "Google US English", "Microsoft Zira", "Samantha",
  "Karen", "Moira", "Tessa", "Fiona", "Victoria",
];
const KNOWN_MALE_VOICES = ["david", "mark", "george", "daniel", "alex", "fred", "guy"];
const FEMALE_NAME_HINTS = ["female", "woman", "zira", "aria", "jenny", "eva", "linda"];

export function selectFemaleVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  if (!voices || voices.length === 0) return null;
  const isEnglish = (v: SpeechSynthesisVoice) => v.lang?.toLowerCase().startsWith("en");
  const isKnownMale = (v: SpeechSynthesisVoice) =>
    KNOWN_MALE_VOICES.some((m) => v.name.toLowerCase().includes(m));
  for (const name of PREFERRED_FEMALE_VOICES) {
    const match = voices.find((v) => isEnglish(v) && v.name.toLowerCase().includes(name.toLowerCase()));
    if (match) return match;
  }
  const hinted = voices.find((v) => isEnglish(v) && FEMALE_NAME_HINTS.some((h) => v.name.toLowerCase().includes(h)));
  if (hinted) return hinted;
  const notMale = voices.find((v) => isEnglish(v) && !isKnownMale(v));
  if (notMale) return notMale;
  return voices.find(isEnglish) ?? null;
}

// Whisper prompt that biases transcription toward form-filling vocabulary
const BASE_HINT = "yes, no, skip, correct, wrong, Jackson, Johnson, Smith, Jones, Williams, Medicare, Medicaid";

// Whisper, primed with the vocabulary hint above, tends to *regurgitate* those words
// when it hears near-silence or the tail of the assistant's own TTS — producing junk
// like "yes, no, skip, correct, yes, no, skip…". Treat a transcript that is mostly
// repeated hint/command words as a non-answer so it never auto-submits.
// Only the words Whisper actually regurgitates from the prompt hint (commands + the
// name/field vocabulary). Pure grammar words ("the", "a", "of") were removed: they
// appear in almost every genuine answer, so counting them made real multi-word replies
// like "yes the address is correct" tip over the 0.7 ratio and get wrongly discarded.
const _HALLUCINATION_TOKENS = new Set([
  "yes", "no", "skip", "correct", "wrong", "yeah", "yep", "nope", "okay", "ok",
  "sure", "jackson", "johnson", "smith", "jones", "williams", "medicare",
  "medicaid", "patient", "name", "address", "date", "birth",
]);
function isLikelyHallucination(text: string): boolean {
  const tokens = text.toLowerCase().replace(/[.,!?;:'"-]/g, " ").split(/\s+/).filter(Boolean);
  if (tokens.length < 4) return false; // genuine short answers ("yes", "skip") are fine
  const hits = tokens.filter((t) => _HALLUCINATION_TOKENS.has(t)).length;
  return hits / tokens.length >= 0.7;
}

// Silence detection tuning
const SILENCE_THRESHOLD = 20;   // RMS below this = silent (0–255 scale); raised to ignore background noise
const SILENCE_GRACE_MS  = 1800; // stop after this many ms of continuous silence
const MIN_SPEECH_MS     = 600;  // don't stop before this even if silent (catch short words)
const MAX_RECORDING_MS  = 20000; // hard stop so background noise can never hold the mic forever
// Browser SpeechRecognition: keep the mic open across natural pauses and only finalize
// after this much silence following the last (interim or final) result, so a mid-answer
// pause doesn't cut the speaker off.
const SR_END_SILENCE_MS = 1400;
// Initial window before ANY speech is heard — a silent mic settles after this (then the
// hands-free re-arm decides what to do) instead of holding "Listening…" for MAX_RECORDING_MS.
const SR_NO_SPEECH_MS = 6500;
const BROWSER_VOICE_WAIT_MS = 600; // Chrome can delay voice loading without firing voiceschanged
// Safety-net ceiling for the browser-TTS "release the turn" timer. Must comfortably
// exceed the real spoken duration of the longest message (the canned greeting can be
// ~30s) so the REAL utt.onend fires first; a too-low cap releases mid-speech and opens
// the mic while Mia is still talking (her voice echoes into STT).
const BROWSER_TTS_MAX_MS = 45000;

// `??` so an explicitly-empty value routes through the same-origin /api proxy; see lib/api.ts.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// 🔒 Browser SpeechRecognition (Chrome/Edge) streams mic audio to Google's speech
// service — fine for a local mock/demo, NOT for real PHI. Set
// NEXT_PUBLIC_FORCE_SERVER_STT=1 to force the server Whisper path (audio stays on the
// already-configured OpenAI-compatible endpoint) for any real deployment.
const FORCE_SERVER_STT = (process.env.NEXT_PUBLIC_FORCE_SERVER_STT ?? "0") === "1";

async function transcribeBlob(blob: Blob, hint: string, formId = ""): Promise<string> {
  const form = new FormData();
  form.append("audio", blob, "audio.webm");
  form.append("prompt", hint);
  if (formId) form.append("form_id", formId);
  const res = await fetch(`${API_BASE}/api/stt`, { method: "POST", body: form, signal: AbortSignal.timeout(20000) });
  if (!res.ok) throw new Error(`STT ${res.status}`);
  const data = await res.json();
  return (data.transcript ?? "").trim();
}

export function useVoice({ onTranscript, onError, onNoSpeech, hint = "", formId = "" }: UseVoiceOptions = {}) {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [transcript, setTranscript] = useState("");
  const [supported, setSupported] = useState(false);

  // TTS refs
  const synthRef        = useRef<SpeechSynthesis | null>(null);
  const utteranceRef    = useRef<SpeechSynthesisUtterance | null>(null);
  const audioCtxRef     = useRef<AudioContext | null>(null);
  const audioSourceRef  = useRef<AudioBufferSourceNode | null>(null);
  // Incremented every time stopSpeaking is called — checked inside async tts callbacks
  // so in-flight ElevenLabs audio never starts playing after stop was requested.
  const speakGenRef     = useRef(0);
  // Prefetch cache: text -> Promise<ArrayBuffer | null>
  const ttsCacheRef     = useRef<Map<string, Promise<ArrayBuffer | null>>>(new Map());

  // STT refs
  const recognitionRef     = useRef<any>(null);   // browser SpeechRecognition (primary)
  const srSilenceTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null); // end-of-speech debounce for SpeechRecognition
  const mediaRecorderRef   = useRef<MediaRecorder | null>(null);
  const chunksRef          = useRef<Blob[]>([]);
  // Warm mic stream — acquired once, reused across turns so startListening is instant
  const warmStreamRef      = useRef<MediaStream | null>(null);
  const wantListeningRef   = useRef(false);
  // Silence detection
  const analyserRef        = useRef<AnalyserNode | null>(null);
  const silenceTimerRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxListenTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const speechStartRef     = useRef<number>(0);
  const silenceRafRef      = useRef<number | null>(null);
  // Set true once clear speech (well above the calibrated floor) is heard, so a
  // recording of pure silence/echo is dropped instead of sent to Whisper.
  const sawSpeechRef       = useRef(false);

  // Stable callback refs
  const onTranscriptRef = useRef(onTranscript);
  const onErrorRef      = useRef(onError);
  const onNoSpeechRef   = useRef(onNoSpeech);
  const hintRef         = useRef(hint);
  const formIdRef      = useRef(formId);
  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);
  useEffect(() => { onNoSpeechRef.current = onNoSpeech; }, [onNoSpeech]);
  useEffect(() => { hintRef.current = hint; }, [hint]);
  useEffect(() => {
    formIdRef.current = formId;
    ttsCacheRef.current.clear();
  }, [formId]);

  useEffect(() => {
    const hasSynth = typeof window !== "undefined" && "speechSynthesis" in window;
    const hasMedia = typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
    const ok = hasSynth && hasMedia;
    setSupported(ok);
    if (!ok) setStatus("unsupported");
    if (hasSynth) synthRef.current = window.speechSynthesis;
  }, []);

  /* ─── Warm mic: acquire once, keep open ─── */

  const ensureWarmStream = useCallback(async (): Promise<MediaStream | null> => {
    if (warmStreamRef.current?.active) return warmStreamRef.current;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl:  true,
          sampleRate:       16000,
        },
      });
      warmStreamRef.current = stream;
      log("warm mic acquired");
      return stream;
    } catch (e: any) {
      log("getUserMedia failed", e?.name);
      setStatus("error");
      onErrorRef.current?.("Microphone access denied. Please allow microphone in browser settings.");
      return null;
    }
  }, []);

  /* ─── Silence detection loop ─── */

  const stopSilenceDetection = useCallback(() => {
    if (silenceRafRef.current !== null) {
      cancelAnimationFrame(silenceRafRef.current);
      silenceRafRef.current = null;
    }
    if (silenceTimerRef.current !== null) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const clearMaxListenTimer = useCallback(() => {
    if (maxListenTimerRef.current !== null) {
      clearTimeout(maxListenTimerRef.current);
      maxListenTimerRef.current = null;
    }
  }, []);

  // stopListening forward-declared so silence detector can call it
  const stopListeningRef = useRef<() => void>(() => {});

  const startSilenceDetection = useCallback((stream: MediaStream) => {
    // Reuse the existing AudioContext if open, otherwise create one
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new AudioContext();
    }
    const ctx = audioCtxRef.current;
    // A suspended context (autoplay policy) starves the analyser, so silence
    // detection would see flat zeros and never register speech — resume it.
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    const source  = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    analyserRef.current = analyser;

    const buf = new Uint8Array(analyser.frequencyBinCount);
    // Calibration: collect ambient RMS samples for the first 500ms, then set
    // the effective threshold = max(SILENCE_THRESHOLD, ambient * 2.5).
    // This adapts to the room — a quiet room stays sensitive, a noisy room
    // raises the bar so background chatter doesn't count as speech.
    const CALIBRATION_MS = 500;
    let calibrationSamples: number[] = [];
    let effectiveThreshold = SILENCE_THRESHOLD;

    const tick = () => {
      if (!wantListeningRef.current) return;
      analyser.getByteTimeDomainData(buf);

      // RMS of the waveform centred at 128 (silence = flat 128 line)
      let sumSq = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = buf[i] - 128;
        sumSq += v * v;
      }
      const rms = Math.sqrt(sumSq / buf.length);
      const elapsed = Date.now() - speechStartRef.current;

      // Calibration phase — measure ambient noise floor
      if (elapsed < CALIBRATION_MS) {
        calibrationSamples.push(rms);
        silenceRafRef.current = requestAnimationFrame(tick);
        return;
      }
      if (calibrationSamples.length > 0) {
        const ambientMax = Math.max(...calibrationSamples);
        effectiveThreshold = Math.max(SILENCE_THRESHOLD, ambientMax * 2.5);
        log("calibrated threshold:", effectiveThreshold.toFixed(1), "ambient max:", ambientMax.toFixed(1));
        calibrationSamples = [];
      }

      if (rms < effectiveThreshold) {
        // Silence detected — start the grace-period timer (only after min speech time)
        if (silenceTimerRef.current === null && elapsed > MIN_SPEECH_MS) {
          silenceTimerRef.current = setTimeout(() => {
            log("silence detected — auto-stopping");
            stopListeningRef.current();
          }, SILENCE_GRACE_MS);
        }
      } else {
        // Real speech — remember we heard it, and cancel any pending silence timer.
        if (rms > effectiveThreshold * 1.4) sawSpeechRef.current = true;
        if (silenceTimerRef.current !== null) {
          clearTimeout(silenceTimerRef.current);
          silenceTimerRef.current = null;
        }
      }

      silenceRafRef.current = requestAnimationFrame(tick);
    };

    silenceRafRef.current = requestAnimationFrame(tick);
  }, []);

  /* ─── TTS ─── */

  const stopSpeaking = useCallback(() => {
    speakGenRef.current += 1; // invalidate any in-flight tts promise
    try { audioSourceRef.current?.stop(); } catch {}
    audioSourceRef.current = null;
    synthRef.current?.cancel();
    setStatus("idle");
  }, []);

  const prefetchTts = useCallback((text: string) => {
    const currentFormId = formIdRef.current;
    const cacheKey = `${currentFormId}::${text}`;
    if (!text || ttsCacheRef.current.has(cacheKey)) return;
    ttsCacheRef.current.set(cacheKey, api.tts(text, currentFormId));
    // Evict old entries beyond 5 to avoid unbounded growth
    if (ttsCacheRef.current.size > 5) {
      const firstKey = ttsCacheRef.current.keys().next().value;
      if (firstKey) ttsCacheRef.current.delete(firstKey);
    }
  }, []);

  const speak = useCallback((text: string, onEnd?: () => void, onStart?: () => void) => {
    speakGenRef.current += 1;
    const myGen = speakGenRef.current;
    try { audioSourceRef.current?.stop(); } catch {}
    audioSourceRef.current = null;
    synthRef.current?.cancel();
    setStatus("speaking");

    // Use prefetched buffer if available, otherwise fetch now
    const currentFormId = formIdRef.current;
    const cacheKey = `${currentFormId}::${text}`;
    const bufPromise = ttsCacheRef.current.get(cacheKey) ?? api.tts(text, currentFormId);
    ttsCacheRef.current.delete(cacheKey); // consume from cache

    bufPromise.then((buf) => {
      if (speakGenRef.current !== myGen) return; // stopSpeaking called while in-flight
      if (!buf || buf.byteLength === 0) { _speakBrowser(text, onEnd, onStart); return; }
      if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
        audioCtxRef.current = new AudioContext();
      }
      const ctx = audioCtxRef.current;
      ctx.decodeAudioData(buf).then((decoded) => {
        if (speakGenRef.current !== myGen) return; // stopped while decoding
        const source = ctx.createBufferSource();
        source.buffer = decoded;
        source.connect(ctx.destination);
        audioSourceRef.current = source;

        // Fire the "done speaking" handler exactly once. A safety timer guarantees
        // it runs even if the browser blocks/suspends audio and `onended` never
        // fires — otherwise a hands-free flow waiting on onEnd would dead-end.
        let ended = false;
        const finishSpeaking = () => {
          if (ended || speakGenRef.current !== myGen) return;
          ended = true;
          audioSourceRef.current = null;
          setStatus("idle");
          onEnd?.();
        };
        source.onended = finishSpeaking;

        const startPlayback = () => {
          onStart?.(); // audio is about to start — show the question bubble now
          try { source.start(0); } catch { /* already started / invalid state */ }
        };
        // Autoplay policy: a context created without a user gesture starts
        // "suspended" — resume it so audio actually plays and onended can fire.
        if (ctx.state === "suspended") {
          ctx.resume().then(startPlayback).catch(startPlayback);
        } else {
          startPlayback();
        }
        // Safety net: advance the conversation after the clip's duration even if
        // audio was blocked (silent first-load greeting must not hang the flow).
        setTimeout(finishSpeaking, Math.ceil((decoded.duration || 2) * 1000) + 1200);
      }).catch(() => {
        if (speakGenRef.current !== myGen) return;
        setStatus("idle");
        _speakBrowser(text, onEnd, onStart);
      });
    }).catch(() => {
      if (speakGenRef.current !== myGen) return;
      _speakBrowser(text, onEnd, onStart);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const _speakBrowser = useCallback((text: string, onEnd?: () => void, onStart?: () => void) => {
    const synth = synthRef.current;
    const myGen = speakGenRef.current;
    if (!synth) { setStatus("idle"); onStart?.(); onEnd?.(); return; }

    let started = false;
    let realStart = false; // true only once the OS engine actually starts speaking
    let finished = false;
    let voiceTimer: ReturnType<typeof setTimeout> | null = null;
    let finishTimer: ReturnType<typeof setTimeout> | null = null;
    let neverStartedTimer: ReturnType<typeof setTimeout> | null = null;

    const clearTimers = () => {
      if (voiceTimer !== null) {
        clearTimeout(voiceTimer);
        voiceTimer = null;
      }
      if (finishTimer !== null) {
        clearTimeout(finishTimer);
        finishTimer = null;
      }
      if (neverStartedTimer !== null) {
        clearTimeout(neverStartedTimer);
        neverStartedTimer = null;
      }
    };

    const markStarted = () => {
      if (started || speakGenRef.current !== myGen) return;
      started = true;
      setStatus("speaking");
      onStart?.();
    };

    const finish = (callEnd = true) => {
      if (finished || speakGenRef.current !== myGen) return;
      finished = true;
      clearTimers();
      utteranceRef.current = null;
      setStatus("idle");
      if (callEnd) onEnd?.();
    };

    const doSpeak = () => {
      if (finished || speakGenRef.current !== myGen) return;
      const activeSynth = synthRef.current;
      if (!activeSynth) { finish(true); return; }

      const utt = new SpeechSynthesisUtterance(text);
      utt.lang = "en-US";
      utt.rate = 0.95;
      utt.pitch = 1;
      const voices = activeSynth.getVoices();
      const preferred = selectFemaleVoice(voices);
      if (preferred) utt.voice = preferred;
      utt.onstart = () => { realStart = true; markStarted(); };
      utt.onend = () => finish(true);
      utt.onerror = (e) => {
        const error = (e as any).error;
        finish(error !== "interrupted" && error !== "canceled");
      };

      utteranceRef.current = utt;
      setStatus("speaking");
      try {
        activeSynth.speak(utt);
      } catch {
        finish(true);
        return;
      }
      // Some browsers never emit onstart/onend when speech is blocked or voices
      // are still initializing. Show the message and release the turn anyway.
      setTimeout(markStarted, 150);
      // If the engine never ACTUALLY starts speaking (autoplay-blocked/muted), release
      // the turn quickly so we don't sit on a silent "Speaking…" for the whole estimate.
      neverStartedTimer = setTimeout(() => { if (!realStart) finish(true); }, 4000);
      // SAFETY NET for when speech DID start but `onend` never fires — keep it generous
      // (up to BROWSER_TTS_MAX_MS) so a slowly-spoken greeting finishes for real (via
      // utt.onend) before it fires. An under-estimate would release the turn mid-speech
      // and open the mic while Mia is still talking, feeding her own voice into STT.
      const estimatedMs = Math.min(BROWSER_TTS_MAX_MS, Math.max(3500, text.length * 100 + 2500));
      finishTimer = setTimeout(() => finish(true), estimatedMs);
    };

    const voices = synth.getVoices();
    if (voices.length > 0) {
      setTimeout(doSpeak, 50);
    } else {
      synth.onvoiceschanged = () => {
        if (synthRef.current) synthRef.current.onvoiceschanged = null;
        if (voiceTimer !== null) {
          clearTimeout(voiceTimer);
          voiceTimer = null;
        }
        setTimeout(doSpeak, 50);
      };
      voiceTimer = setTimeout(() => {
        if (synthRef.current) synthRef.current.onvoiceschanged = null;
        doSpeak();
      }, BROWSER_VOICE_WAIT_MS);
    }
  }, []);

  /* ─── STT core ─── */

  const finishRecording = useCallback(async (chunks: Blob[], mimeType: string) => {
    const blob = new Blob(chunks, { type: mimeType || "audio/webm" });
    // The MediaRecorder captures the real mic audio regardless of the analyser, so
    // we gate only on a too-short clip here. (The analyser-based "energy gate" was
    // removed: a suspended AudioContext makes the analyser read flat zeros, which
    // wrongly discarded real speech. The post-transcription hallucination filter
    // below is what blocks Whisper's silence/echo "yes, no, skip" garbage.)
    if (blob.size < 1400) {
      log("recording too short, skipping");
      setStatus("idle");
      onNoSpeechRef.current?.();
      return;
    }
    setStatus("processing");
    const fullHint = [BASE_HINT, hintRef.current].filter(Boolean).join(", ");
    try {
      const text = await transcribeBlob(blob, fullHint, formIdRef.current);
      log("whisper transcript:", text);
      if (text && isLikelyHallucination(text)) {
        log("discarded hallucinated transcript:", text);
        setStatus("idle");
        onNoSpeechRef.current?.();
        return;
      }
      if (text) {
        // Return to idle before handing the transcript to the page. The page may
        // ignore a duplicate while an agent turn is in flight; voice must not stay
        // stuck in "processing" in that case.
        setStatus("idle");
        setTranscript(text);
        onTranscriptRef.current?.(text);
      } else {
        setStatus("idle");
        onNoSpeechRef.current?.();
      }
    } catch (err) {
      log("transcription error:", err);
      onErrorRef.current?.("I didn't catch that — tap the mic to try again, or type your answer.");
      setStatus("idle");
      onNoSpeechRef.current?.();
    }
  }, []);

  const stopListening = useCallback(() => {
    log("stopListening");
    wantListeningRef.current = false;
    clearMaxListenTimer();
    if (srSilenceTimerRef.current !== null) { clearTimeout(srSilenceTimerRef.current); srSilenceTimerRef.current = null; }
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch {}
      recognitionRef.current = null;
    }
    stopSilenceDetection();
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      try { mediaRecorderRef.current.stop(); } catch {}
    } else {
      setStatus("idle");
    }
    // Do NOT release warmStreamRef — keep it for the next turn
  }, [clearMaxListenTimer, stopSilenceDetection]);

  // Keep the ref in sync so the silence detector can call it without a stale closure
  useEffect(() => { stopListeningRef.current = stopListening; }, [stopListening]);

  const startListening = useCallback(async () => {
    log("startListening");
    // Idempotent guard: never layer a second engine on the same mic. Overlapping
    // timers (speakReply onEnd, toggleMic, rearm) could otherwise start twice.
    if (wantListeningRef.current && (recognitionRef.current || mediaRecorderRef.current?.state === "recording")) {
      log("already listening — ignoring duplicate start");
      return;
    }
    clearMaxListenTimer();
    // Tear down any half-stopped prior engine before starting fresh.
    if (recognitionRef.current) { try { recognitionRef.current.stop(); } catch {} recognitionRef.current = null; }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      try { mediaRecorderRef.current.stop(); } catch {}
    }
    stopSilenceDetection();
    wantListeningRef.current = true;
    setStatus("listening");

    // Primary path: browser-native SpeechRecognition. It owns the mic, detects the
    // start/end of speech itself, and returns a transcript — no AudioContext, no
    // silence timer, no Whisper hallucination. Reliable in Chrome/Edge.
    // Disabled when FORCE_SERVER_STT is set (PHI deployments use server Whisper).
    const SR: any = typeof window !== "undefined"
      ? ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)
      : null;
    if (SR && !FORCE_SERVER_STT) {
      try {
        const rec = new SR();
        rec.lang = "en-US";
        // continuous + interim so a natural pause mid-answer does NOT end the session
        // and cut the speaker off. We accumulate the final transcript and decide when
        // the user has finished — a short silence (SR_END_SILENCE_MS) after the last
        // result — then stop() and submit once from onend.
        rec.interimResults = true;
        rec.continuous = true;
        rec.maxAlternatives = 1;
        let finalText = "";
        let lastInterim = ""; // fallback if the engine ends before the tail turns final
        const clearSrSilence = () => {
          if (srSilenceTimerRef.current !== null) {
            clearTimeout(srSilenceTimerRef.current);
            srSilenceTimerRef.current = null;
          }
        };
        const scheduleFinalize = (delay: number) => {
          clearSrSilence();
          srSilenceTimerRef.current = setTimeout(() => {
            srSilenceTimerRef.current = null;
            if (recognitionRef.current === rec) { try { rec.stop(); } catch {} }
          }, delay);
        };
        rec.onresult = (e: any) => {
          let interim = "";
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const seg = e.results[i][0]?.transcript ?? "";
            if (e.results[i].isFinal) finalText += seg;
            else interim += seg;
          }
          if (interim.trim()) lastInterim = interim;
          // Speech heard — switch from the initial no-speech window to the short
          // end-of-answer debounce and keep pushing it back while the user talks, so a
          // natural pause never cuts them off.
          if (interim.trim() || finalText.trim()) scheduleFinalize(SR_END_SILENCE_MS);
        };
        rec.onerror = (e: any) => {
          log("SpeechRecognition error:", e?.error);
          if (e?.error === "not-allowed" || e?.error === "service-not-allowed") {
            wantListeningRef.current = false;
            clearMaxListenTimer();
            clearSrSilence();
            setStatus("error");
            onErrorRef.current?.("Microphone access is blocked. Allow the mic in your browser, then try again.");
          }
        };
        rec.onend = () => {
          clearMaxListenTimer();
          clearSrSilence();
          recognitionRef.current = null;
          const text = (finalText.trim() || lastInterim.trim());
          // `wanted` is false only when stopListening() tore this listen down (user
          // tapped Stop, or chose a chip / typed while listening). In that case DON'T
          // submit — otherwise a stale voice answer lands on the NEXT question.
          const wanted = wantListeningRef.current;
          wantListeningRef.current = false;
          if (wanted && text && !isLikelyHallucination(text)) {
            log("SpeechRecognition final:", text);
            // Go straight to "processing" (not "idle") so the pill reads Thinking… with
            // no ~250ms "Ready" flash before the send fires.
            setStatus("processing");
            setTranscript(text);
            onTranscriptRef.current?.(text);
          } else {
            setStatus("idle");
            if (wanted) onNoSpeechRef.current?.();
          }
        };
        recognitionRef.current = rec;
        rec.start();
        // No result yet: arm a longer initial window so a silent mic doesn't hold
        // "Listening…" open for the full MAX_RECORDING_MS; onresult shortens it to the
        // end-of-answer debounce once the user actually speaks.
        scheduleFinalize(SR_NO_SPEECH_MS);
        maxListenTimerRef.current = setTimeout(() => {
          if (recognitionRef.current === rec) {
            log("max listen duration reached - stopping SpeechRecognition");
            try { rec.stop(); } catch {}
          }
        }, MAX_RECORDING_MS);
        log("SpeechRecognition started");
        return;
      } catch (err) {
        log("SpeechRecognition unavailable, falling back to recorder:", err);
        clearMaxListenTimer();
      }
    }

    // Fallback path: MediaRecorder + server Whisper (browsers without SpeechRecognition).
    const stream = await ensureWarmStream();
    if (!stream) return; // permission denied — error already set

    // If the user cancelled while we were awaiting the stream
    if (!wantListeningRef.current) return;

    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"]
      .find((m) => MediaRecorder.isTypeSupported(m)) ?? "";

    chunksRef.current = [];
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    } catch {
      recorder = new MediaRecorder(stream);
    }
    mediaRecorderRef.current = recorder;
    speechStartRef.current = Date.now();
    sawSpeechRef.current = false; // reset per recording for the energy gate

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = () => {
      clearMaxListenTimer();
      stopSilenceDetection();
      if (mediaRecorderRef.current === recorder) mediaRecorderRef.current = null;
      finishRecording([...chunksRef.current], mimeType);
      chunksRef.current = [];
    };

    try {
      recorder.start(200);
    } catch (e) {
      log("recorder.start failed", e);
      clearMaxListenTimer();
      setStatus("idle");
      onNoSpeechRef.current?.();
      return;
    }
    maxListenTimerRef.current = setTimeout(() => {
      if (wantListeningRef.current && mediaRecorderRef.current?.state === "recording") {
        log("max listen duration reached - auto-stopping");
        stopListeningRef.current();
      }
    }, MAX_RECORDING_MS);
    startSilenceDetection(stream);
    log("recorder started", { mimeType });
  }, [clearMaxListenTimer, ensureWarmStream, startSilenceDetection, stopSilenceDetection, finishRecording]);

  const clearTranscript = useCallback(() => setTranscript(""), []);

  // Resume the AudioContext from a user gesture so first-load TTS/STT aren't blocked
  // by the browser autoplay policy (a suspended context plays no sound and never
  // fires `onended`, which would stall a hands-free conversation).
  const unlockAudio = useCallback(() => {
    try {
      if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
        audioCtxRef.current = new AudioContext();
      }
      if (audioCtxRef.current.state === "suspended") audioCtxRef.current.resume().catch(() => {});
    } catch { /* AudioContext unavailable */ }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      synthRef.current?.cancel();
      wantListeningRef.current = false;
      clearMaxListenTimer();
      if (srSilenceTimerRef.current !== null) { clearTimeout(srSilenceTimerRef.current); srSilenceTimerRef.current = null; }
      try { recognitionRef.current?.stop(); } catch {}
      recognitionRef.current = null;
      stopSilenceDetection();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        try { mediaRecorderRef.current.stop(); } catch {}
      }
      // Release warm stream on unmount
      warmStreamRef.current?.getTracks().forEach((t) => t.stop());
      warmStreamRef.current = null;
    };
  }, [clearMaxListenTimer, stopSilenceDetection]);

  return {
    status,
    transcript,
    supported,
    speak,
    stopSpeaking,
    startListening,
    stopListening,
    clearTranscript,
    prefetchTts,
    unlockAudio,
  };
}
