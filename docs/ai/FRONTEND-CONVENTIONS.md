# Frontend conventions (Next.js 14 / React 18 / TypeScript)

> How the existing UI is written. Match it.

## App Router & rendering

- Next.js 14 **App Router** under `frontend/app/`. Routes:
  `/`, `/patient-match`, `/assistant/[sessionId]`, `/review/[sessionId]`,
  `/admin`, `/admin/dashboard`.
- Pages are **client components** (`"use client"` at top) because they hold form
  state, talk to the API, and use voice/browser APIs. Keep new interactive pages
  client components; only make something a server component if it has no client
  state and no browser API use.
- `app/layout.tsx` is the root layout (header/footer + the disclaimer). Global
  styles + Tailwind layers live in `app/globals.css`.

## API access — always via `lib/api.ts`

- One typed client object `api` wraps `fetch`. The base URL is
  `process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"`.
- **Never call `fetch` to the backend directly from a component.** Add a method
  to `api` instead, returning a typed value from `lib/types.ts`.
- The internal `request<T>(path, options)` helper throws on non-2xx (reads the
  body into the error). Callers wrap calls in `try/catch` and set an `error`
  state; show a friendly message (`err instanceof Error ? err.message : "..."`).
- TTS/voice degrade gracefully: `api.tts` returns `null` on failure and the page
  falls back to browser `speechSynthesis`.

## Types

- All shared types live in `lib/types.ts` (e.g. `MaskedPatient`, `SessionState`,
  `NextQuestion`, `AnswerResult`, `ReviewResponse`, `GeneratePdfResponse`). Add
  new shapes there; don't inline interfaces in components for shared data.
- `strict: true` is on. No implicit `any`. Path alias `@/*` -> repo root.

## Components

- Function components, props typed with an explicit `interface`/type. Callback
  props use the `onX` convention (`onSelect`, `onSubmit`, `onSkip`).
- Reusable presentational pieces live in `components/`. Page-local helpers
  (panels, modals, small indicators) may be defined inline in the page file —
  that's an established pattern here; promote to `components/` only when reused.
- No external UI/component library — styling is **Tailwind utilities** + a few
  shared classes in `globals.css` (`.bubble-ai`, `.bubble-user`, `.ai-orb`,
  pills/badges). Reuse those classes; match the `ai-*` / `surface-*` palette in
  `tailwind.config.ts`.

## State & navigation

- Local state via `useState`/`useRef`; no Redux/Zustand. That's appropriate —
  don't add a state library for this app's size.
- Navigation via `useRouter()` / `useParams()` from `next/navigation`.
- Cross-page handoff:
  - Patient search results -> `sessionStorage` (`patientSearchResult`,
    `patientSearchInput`).
  - Chat history -> `localStorage["chat_messages_<sessionId>"]`.
  - Admin token -> `localStorage["admin_token"]` (sent as `Authorization:
    Bearer`). Note the XSS trade-off (backlog item); keep tokens out of URLs.
- The `sessionId` is the spine: created by `POST /api/session/create`, carried in
  the route param, used for every subsequent call.

## Voice (`lib/useVoice.ts`)

- One hook owns STT + TTS. STT records via `MediaRecorder` with RMS-based silence
  detection and posts the blob to `/api/stt`; TTS posts to `/api/tts` and falls
  back to browser `speechSynthesis`.
- Web Speech API shims are in `types/speech.d.ts`. Voice is **off for sensitive,
  non-date fields**. Keep that guard when touching voice.
- Don't block the typed flow on voice — typing must always work.

## Accessibility & UX (raise the bar when you touch a component)

- Add `aria-label`s to icon-only buttons (mic, voice toggle). Don't rely on
  color alone for state — pair with text/icon.
- The 3-column assistant layout is not yet responsive (backlog). If you edit it,
  prefer adding responsive breakpoints over making it worse.

## Config

- `next.config.js` is minimal (`reactStrictMode: true`). `tailwind.config.ts`
  defines the `ai-*`/`surface-*` palette and content globs. `tsconfig.json`:
  strict, `@/*` alias, bundler resolution.
- Only `NEXT_PUBLIC_*` env vars are available in the browser. Today only
  `NEXT_PUBLIC_API_BASE_URL` is used.

## Commands

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run build    # production build (also the typecheck gate)
npm run lint     # eslint (next/core-web-vitals)
```

> There is no frontend test setup yet (backlog). When adding tests, prefer
> Playwright for the multi-page flow and React Testing Library for components.
