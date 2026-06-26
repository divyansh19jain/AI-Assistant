"""
Knowledgebase (RAG) — embed per-form guidance docs and retrieve relevant snippets.

Used by the AI to *help the user understand a question* ("what counts as income?",
"who is in my household?"). Design choices that keep it simple, offline-capable, and
testable:

- **Embeddings:** OpenAI ``text-embedding-3-small`` when ``OPENAI_API_KEY`` is set;
  otherwise a deterministic **local hashing embedding** so retrieval works with no
  API key (and tests run offline). Ingest + query always use the same function within
  a deployment, so the vector space is consistent.
- **Storage:** embeddings live as JSON text on :class:`KbChunk`; similarity is plain
  cosine in Python. No pgvector extension required (it can be a prod optimization).

🔒 PHI: KB content is form-level guidance only. Retrieval queries are built from
**field-level text** (label / question), never the patient's raw answer — so we never
send patient data to the embedding API or store it in the index.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re

logger = logging.getLogger(__name__)

_LOCAL_DIM = 256
_CHUNK_CHARS = 800
_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ── embedding ───────────────────────────────────────────────────────────────
def _local_embed_one(text: str) -> list[float]:
    """Deterministic, dependency-free bag-of-words hashing embedding (normalized)."""
    vec = [0.0] * _LOCAL_DIM
    for tok in _TOKEN_RE.findall(text.lower()):
        bucket = int(hashlib.md5(tok.encode()).hexdigest(), 16) % _LOCAL_DIM
        vec[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _openai_embed(texts: list[str]) -> list[list[float]] | None:
    """OpenAI embeddings, or None when no key / on failure (caller falls back local)."""
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
        return [d.embedding for d in resp.data]
    except Exception:
        logger.warning("OpenAI embedding failed; using local fallback.", exc_info=True)
        return None


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts (OpenAI if configured, else the local fallback)."""
    if not texts:
        return []
    return _openai_embed(texts) or [_local_embed_one(t) for t in texts]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ── chunking ────────────────────────────────────────────────────────────────
def chunk_text(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    """Split text into ~``size``-char chunks on paragraph/sentence boundaries."""
    text = (text or "").strip()
    if not text:
        return []
    paras = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""
    for para in paras:
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 1 <= size:
            buf = f"{buf}\n{para}".strip()
        else:
            if buf:
                chunks.append(buf)
            # A single oversized paragraph is hard-split.
            while len(para) > size:
                chunks.append(para[:size])
                para = para[size:]
            buf = para
    if buf:
        chunks.append(buf)
    return chunks


# ── ingest / retrieve (DB-backed) ────────────────────────────────────────────
def ingest_document(db, document) -> int:
    """(Re)embed one :class:`KbDocument`: replace its chunks, set status. Returns chunk count.

    Best-effort: marks the document ``failed`` and returns 0 on error rather than raising.
    """
    from app.db.models import KbChunk

    try:
        db.query(KbChunk).filter(KbChunk.kb_document_id == document.id).delete()
        pieces = chunk_text(document.text)
        vectors = embed_texts(pieces)
        for i, (piece, vec) in enumerate(zip(pieces, vectors)):
            db.add(
                KbChunk(
                    kb_document_id=document.id,
                    form_id=document.form_id,
                    ordinal=i,
                    chunk_text=piece,
                    embedding=json.dumps(vec),
                )
            )
        document.status = "embedded" if pieces else "failed"
        db.commit()
        return len(pieces)
    except Exception:
        db.rollback()
        logger.warning("KB ingest failed for document %s.", getattr(document, "id", "?"), exc_info=True)
        try:
            document.status = "failed"
            db.commit()
        except Exception:
            db.rollback()
        return 0


def retrieve(db, form_id: str, query: str, k: int = 3) -> list[str]:
    """Return up to ``k`` KB chunk texts most relevant to ``query`` for ``form_id``.

    Returns ``[]`` when the form has no embedded KB (graceful disable). The ``query``
    must be PHI-free field-level text (see module note) — callers pass the field
    label/question, never the patient's answer.
    """
    from app.db.models import KbChunk

    try:
        rows = db.query(KbChunk).filter(KbChunk.form_id == form_id, KbChunk.embedding.isnot(None)).all()
        if not rows:
            return []
        qvec = embed_texts([query])[0]
        scored = []
        for r in rows:
            try:
                vec = json.loads(r.embedding)
            except Exception:
                continue
            scored.append((_cosine(qvec, vec), r.chunk_text))
        scored.sort(key=lambda t: t[0], reverse=True)
        # Drop near-zero matches so unrelated KBs don't inject noise.
        return [text for score, text in scored[:k] if score > 0.01]
    except Exception:
        logger.warning("KB retrieval failed for form %s.", form_id, exc_info=True)
        return []
