# AI / LLM integration

> The "AI" in AI-Assistant is a set of narrow NLP helpers around a deterministic
> form engine. The LLM is **optional**: with no API key the app runs fully on
> rule-based logic. Keep it that way.

## Single entry point: `app/ai/llm.py`

Everything goes through one factory. **Never construct a provider client
elsewhere.**

- `get_chat_model() -> model | None` — builds and caches (`lru_cache`) the chat
  model from `Settings`. Returns `None` when the provider is unsupported, the
  key is missing, or construction fails.
- `structured_model(schema) -> bound_model | None` — `get_chat_model()` plus
  `.with_structured_output(schema, method="json_schema")` for validated,
  schema-constrained output. Keep schemas conservative (strict json_schema mode
  rejects exotic unions/constraints).
- `ai_enabled() -> bool` — `True` when a real model is constructable.

## Current provider (authoritative)

- **OpenAI via `langchain-openai.ChatOpenAI`.** Configured by:
  - `LLM_PROVIDER` (default `"openai"` — only `"openai"` is implemented),
  - `OPENAI_MODEL` (config default `"gpt-5.4-mini"`),
  - `OPENAI_API_KEY`, `OPENAI_TEMPERATURE` (default `0.0`).
- `temperature=0.0`, `timeout=30`, `max_retries=2` are set in the factory.

> ⚠️ **Doc drift to be aware of:** the project README still has a "Anthropic /
> Claude (`claude-opus-4-8`)" section. **The code does not use Claude** — there
> is no Anthropic SDK in `requirements.txt` and `llm.py` only builds
> `ChatOpenAI`. Trust the code. Reconciling the README and validating the
> `OPENAI_MODEL` value are tracked in [IMPROVEMENT-BACKLOG.md](./IMPROVEMENT-BACKLOG.md).

## The mandatory fallback pattern

Every AI helper follows the same shape — copy it for any new AI feature:

```python
def do_thing(...):
    # 1. fast deterministic shortcuts (skip words, commands, regex) — no LLM
    if _obvious_case(...):
        return _rule_based(...)

    # 2. LLM path, only if available
    model = structured_model(_Schema)        # or get_chat_model()
    if model is not None:
        try:
            result = model.invoke([("system", SYS), ("human", user)])
            return _from_llm(result)
        except Exception:
            logger.warning("LLM <thing> failed; using fallback.", exc_info=True)

    # 3. deterministic fallback — ALWAYS present, never raises
    return _rule_based(...)
```

The existing helpers that follow it:

- `answer_extractor.py` — extract a normalized value from free text; smart-
  confirm on low confidence; optional semantic sanity-check (skipped for
  sensitive fields).
- `question_rewriter.py` — make the next question conversational/contextual.
- `help_intent.py` — classify "is the user answering, or asking for help?"

## Prompt conventions

- Messages are `[("system", system_prompt), ("human", user_prompt)]` tuples.
- Prefer **structured output** (`structured_model`) over parsing free text.
- Pass field metadata (label, type, validation_rule, question_text, prior
  answers) into the prompt, but **never send `sensitive` field values to the
  LLM** — the existing code guards this; preserve it.
- Keep extraction deterministic (`temperature=0.0`). Don't add creativity.

## Voice / STT / TTS

- `speech_to_text.py` / `tts` services are interface-first with provider
  implementations behind env keys (`DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`,
  `ELEVENLABS_VOICE_ID`, plus OpenAI TTS). With no keys, mocks/browser fallback
  are used. The `/api/stt` and `/api/tts` routers are the only `async` parts.

## LangGraph

- `app/ai/langgraph_flow.py` provides a `StateGraph` orchestration of the answer
  step with a synchronous fallback (`_run_synchronous`) when langgraph isn't
  available. Both paths must produce the same result; if you touch one, keep the
  other in sync.

## Adding a different provider (e.g. Anthropic/Claude) — if ever asked

Do it **only** inside `get_chat_model()` so the rest of the app is unchanged:

1. Add the SDK to `requirements.txt` (e.g. `langchain-anthropic`).
2. Add `ANTHROPIC_API_KEY` (already present in `Settings`) handling and branch on
   `LLM_PROVIDER == "anthropic"` to return `ChatAnthropic(model=..., ...)`.
3. Keep `method="json_schema"` structured output working (or branch the method
   per provider).
4. Everything downstream (`structured_model`, the three helpers, the fallback)
   stays the same. Confirm the rule-based fallback still triggers when the key
   is absent.

> If the user is building/choosing models or debugging tool-calls/streaming,
> verify model IDs and pricing against current provider docs — don't answer
> from memory.
