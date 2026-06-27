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

// Silence detection tuning
const SILENCE_THRESHOLD = 20;   // RMS below this = silent (0–255 scale); raised to ignore background noise
const SILENCE_GRACE_MS  = 1800; // stop after this many ms of continuous silence
const MIN_SPEECH_MS     = 600;  // don't stop before this even if silent (catch short words)

// `??` so an explicitly-empty value routes through the same-origin /api proxy; see lib/api.ts.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function transcribeBlob(blob: Blob, hint: string, formId = ""): Promise<string> {
  const form = new FormData();
  form.append("audio", blob, "audio.webm");
  form.append("prompt", hint);
  if (formId) form.append("form_id", formId);
  const res = await fetch(`${API_BASE}/api/stt`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`STT ${res.status}`);
  const data = await res.json();
  return (data.transcript ?? "").trim();
}

export function useVoice({ onTranscript, onError, hint = "", formId = "" }: UseVoiceOptions = {}) {
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

  // Stable callback refs
  const onTranscriptRef = useRef(onTranscript);
  const onErrorRef      = useRef(onError);
  const hintRef         = useRef(hint);
  const formIdRef      = useRef(formId);
  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);
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
        // Real speech — cancel any pending silence timer
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
        source.onended = () => {
          if (speakGenRef.current !== myGen) return;
          audioSourceRef.current = null;
          setStatus("idle");
          onEnd?.();
        };
        onStart?.(); // audio is about to start — show the question bubble now
        source.start(0);
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
    if (blob.size < 1000) {
      log("blob too small, skipping");
      setStatus("idle");
      return;
    }
    setStatus("processing");
    const fullHint = [BASE_HINT, hintRef.current].filter(Boolean).join(", ");
    try {
      const text = await transcribeBlob(blob, fullHint, formIdRef.current);
      log("whisper transcript:", text);
      if (text) {
        setTranscript(text);
        onTranscriptRef.current?.(text);
      } else {
        setStatus("idle");
      }
    } catch (err) {
      log("transcription error:", err);
      onErrorRef.current?.("Transcription failed — please try again.");
      setStatus("idle");
    }
  }, []);

  const stopListening = useCallback(() => {
    log("stopListening");
    wantListeningRef.current = false;
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
    wantListeningRef.current = true;
    setStatus("listening");

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

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = () => {
      stopSilenceDetection();
      finishRecording([...chunksRef.current], mimeType);
      chunksRef.current = [];
    };

    recorder.start(200);
    startSilenceDetection(stream);
    log("recorder started", { mimeType });
  }, [ensureWarmStream, startSilenceDetection, stopSilenceDetection, finishRecording]);

  const clearTranscript = useCallback(() => setTranscript(""), []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      synthRef.current?.cancel();
      wantListeningRef.current = false;
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
  };
}
