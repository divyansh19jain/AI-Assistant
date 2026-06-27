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
const _HALLUCINATION_TOKENS = new Set([
  "yes", "no", "skip", "correct", "wrong", "yeah", "yep", "nope", "okay", "ok",
  "sure", "jackson", "johnson", "smith", "jones", "williams", "medicare",
  "medicaid", "patient", "name", "address", "date", "of", "birth", "the", "a",
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
  const mediaRecorderRef   = useRef<MediaRecorder | null>(null);
  const chunksRef          = useRef<Blob[]>([]);
  // Warm mic stream — acquired once, reused across turns so startListening is instant
  const warmStreamRef      = useRef<MediaStream | null>(null);
  const wantListeningRef   = useRef(false);
  // Silence detection
  const analyserRef        = useRef<AnalyserNode | null>(null);
  const silenceTimerRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
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
    if (!synthRef.current) { setStatus("idle"); onStart?.(); onEnd?.(); return; }
    const doSpeak = () => {
      if (!synthRef.current) return;
      const utt = new SpeechSynthesisUtterance(text);
      utt.lang = "en-US"; utt.rate = 0.95; utt.pitch = 1;
      const voices = synthRef.current.getVoices();
      const preferred = selectFemaleVoice(voices);
      if (preferred) utt.voice = preferred;
      let started = false;
      utt.onstart = () => { started = true; setStatus("speaking"); onStart?.(); };
      utt.onend   = () => { setStatus("idle"); if (started) onEnd?.(); };
      utt.onerror = (e) => {
        if ((e as any).error === "interrupted") return;
        setStatus("idle"); if (started) onEnd?.();
      };
      utteranceRef.current = utt;
      setStatus("speaking");
      synthRef.current.speak(utt);
    };
    const voices = synthRef.current.getVoices();
    if (voices.length > 0) setTimeout(doSpeak, 50);
    else {
      synthRef.current.onvoiceschanged = () => {
        if (synthRef.current) synthRef.current.onvoiceschanged = null;
        setTimeout(doSpeak, 50);
      };
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
  }, [stopSilenceDetection]);

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
        rec.interimResults = false;
        rec.continuous = false;
        rec.maxAlternatives = 1;
        let got = false;
        rec.onresult = (e: any) => {
          let text = "";
          for (let i = e.resultIndex; i < e.results.length; i++) text += e.results[i][0].transcript;
          text = text.trim();
          log("SpeechRecognition result:", text);
          if (text && !isLikelyHallucination(text)) {
            got = true;
            setTranscript(text);
            onTranscriptRef.current?.(text);
          }
        };
        rec.onerror = (e: any) => {
          log("SpeechRecognition error:", e?.error);
          if (e?.error === "not-allowed" || e?.error === "service-not-allowed") {
            setStatus("error");
            onErrorRef.current?.("Microphone access is blocked. Allow the mic in your browser, then try again.");
          }
        };
        rec.onend = () => {
          recognitionRef.current = null;
          setStatus("idle");
          if (!got && wantListeningRef.current) onNoSpeechRef.current?.();
          wantListeningRef.current = false;
        };
        recognitionRef.current = rec;
        rec.start();
        log("SpeechRecognition started");
        return;
      } catch (err) {
        log("SpeechRecognition unavailable, falling back to recorder:", err);
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
      stopSilenceDetection();
      finishRecording([...chunksRef.current], mimeType);
      chunksRef.current = [];
    };

    try {
      recorder.start(200);
    } catch (e) {
      log("recorder.start failed", e);
      setStatus("idle");
      onNoSpeechRef.current?.();
      return;
    }
    startSilenceDetection(stream);
    log("recorder started", { mimeType });
  }, [ensureWarmStream, startSilenceDetection, stopSilenceDetection, finishRecording]);

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
  }, [stopSilenceDetection]);

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
