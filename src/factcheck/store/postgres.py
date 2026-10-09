"""PostgreSQL + pgvector implementation of the Store protocol.

Tables (see SCHEMA below):
  claims        one row per distinct claim: text, embedding, full-text index, first/last seen
  verdicts      one row per claim per check: label, explanation, sources, spans, persuasion tags
  media         one row per checked image: perceptual hash, file hash, caption, origin signals
  media_claims  links an image to the claims it was checked against

A "check" (one POST /check call) has no table of its own: it is the set of verdict rows and the
media row that share a check_id. Cards are rebuilt from those rows on read. Per-run diagnostics
(stage timings, raw extraction/OCR text) are deliberately NOT stored.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..models import Card, ClaimResult, OriginResult, Post, StoredCheck, Tactic

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2

SCHEMA: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    f"""
    CREATE TABLE IF NOT EXISTS claims (
        id          BIGSERIAL PRIMARY KEY,
        claim_text  TEXT NOT NULL,
        claim_norm  TEXT NOT NULL UNIQUE,           -- lower-cased, whitespace-collapsed
        embedding   VECTOR({EMBEDDING_DIM}) NOT NULL,
        tsv         TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', claim_text)) STORED,
        first_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_claims_embedding ON claims USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS idx_claims_tsv ON claims USING gin (tsv)",
    """
    CREATE TABLE IF NOT EXISTS verdicts (
        id              BIGSERIAL PRIMARY KEY,
        claim_id        BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        check_id        VARCHAR(64) NOT NULL,
        label           TEXT NOT NULL,
        explanation     TEXT NOT NULL DEFAULT '',
        sources         JSONB NOT NULL DEFAULT '[]',
        disputed_spans  JSONB NOT NULL DEFAULT '[]',
        evidence_origin TEXT NOT NULL DEFAULT 'none',
        persuasion      JSONB NOT NULL DEFAULT '[]',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_verdicts_claim ON verdicts (claim_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_verdicts_check ON verdicts (check_id)",
    """
    CREATE TABLE IF NOT EXISTS media (
        id          BIGSERIAL PRIMARY KEY,
        check_id    VARCHAR(64) NOT NULL UNIQUE,
        phash       VARCHAR(16),                     -- 64-bit perceptual hash, hex
        file_hash   CHAR(64),                        -- sha256 of the exact bytes, hex
        caption     TEXT,
        origin      JSONB NOT NULL DEFAULT '{}',     -- credentials / detector signal / status
        persuasion  JSONB NOT NULL DEFAULT '[]',     -- fallback for checks with no claims
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_media_phash ON media (phash) WHERE phash IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_media_file_hash ON media (file_hash) WHERE file_hash IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS media_claims (
        media_id BIGINT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
        claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        PRIMARY KEY (media_id, claim_id)
    )
    """,
]

MAX_CLAIM_DISTANCE = 0.6


def _norm(claim: str) -> str:
    return " ".join(claim.lower().split())


def _j(value: Any, default: Any) -> Any:
    """JSONB columns come back decoded; tolerate raw strings too."""
    if value is None:
        return default
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return value


def _vec(embedding: list[float]) -> str:
    return "[" + ",".join(str(f) for f in embedding) + "]"


class SentenceEmbeddingEncoder:
    """Generates 384-dimensional embeddings using sentence-transformers asynchronously.

    The first call constructs the model, which may download weights and takes seconds.
    That happens in a worker thread under a lock so the event loop keeps running and
    concurrent first calls do not load the model twice.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None
        self._load_lock: asyncio.Lock | None = None

    def _load_model(self):
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model_name)

    async def _get_model(self):
        if self._model is not None:
            return self._model
        if self._load_lock is None:  # created lazily so the encoder can be built outside a loop
            self._load_lock = asyncio.Lock()
        async with self._load_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_model)
        return self._model

    async def encode(self, text_input: str) -> list[float]:
        model = await self._get_model()
        vector = await asyncio.to_thread(model.encode, text_input, normalize_embeddings=True)
        return vector.tolist()


def normalize_db_url(url: str) -> str:
    """Accept the URL shapes hosted Postgres providers hand out and make them asyncpg-ready.

    - `postgres://` and `postgresql://` become `postgresql+asyncpg://`.
    - `sslmode=<x>` (libpq syntax, rejected by asyncpg) becomes `ssl=<x>`.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    query = [("ssl", v) if k == "sslmode" else (k, v) for k, v in query]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class PostgresStore:
    def __init__(
        self,
        db_url: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        phash_max_distance: int = 10,
        encoder: SentenceEmbeddingEncoder | None = None,
    ) -> None:
        self.engine = create_async_engine(normalize_db_url(db_url), echo=False, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.encoder = encoder or SentenceEmbeddingEncoder(model_name=embedding_model)
        self.phash_max_distance = phash_max_distance

    async def init_db(self) -> None:
        """Create the extension, tables and indexes if missing; load the embedding model."""
        async with self.engine.begin() as conn:
            for statement in SCHEMA:
                await conn.execute(text(statement))
        await self.encoder.encode("warm up")

    # ------------------------------------------------------------------ reads

    async def find_media(self, phash: str) -> list[StoredCheck]:
        """Checks whose image hash is within the Hamming distance limit, closest first."""
        if not phash or len(phash) != 16:
            return []
        dist = "bit_count(CAST('x' || phash AS bit(64)) # CAST('x' || CAST(:phash AS text) AS bit(64)))"
        stmt = text(f"""
            SELECT check_id, {dist} AS dist
            FROM media
            WHERE phash IS NOT NULL AND length(phash) = 16
              AND {dist} <= CAST(:max_dist AS int)
            ORDER BY dist ASC, created_at DESC
            LIMIT 20
        """)
        async with self.session_factory() as session:
            rows = (await session.execute(stmt, {"phash": phash, "max_dist": self.phash_max_distance})).fetchall()
            return await self._build_checks(session, [r.check_id for r in rows])

    async def find_claims(self, text_query: str, k: int = 5) -> list[StoredCheck]:
        """Checks holding the stored claims nearest to the query by embedding (cosine)."""
        if not text_query.strip():
            return []
        vector = _vec(await self.encoder.encode(text_query))
        stmt = text("""
            SELECT id, (embedding <=> CAST(:embedding AS vector)) AS distance
            FROM claims
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :n
        """)
        async with self.session_factory() as session:
            rows = (await session.execute(stmt, {"embedding": vector, "n": k * 3})).fetchall()
            claim_ids = [r.id for r in rows if r.distance <= MAX_CLAIM_DISTANCE]
            return await self._checks_for_claims(session, claim_ids, k)

    async def find_claims_by_keyword(self, query: str, k: int = 5) -> list[StoredCheck]:
        """Full-text (keyword) search over claims. Not part of the Store protocol; use it for
        exact-term lookups or a future hybrid search."""
        if not query.strip():
            return []
        stmt = text("""
            SELECT id FROM claims
            WHERE tsv @@ websearch_to_tsquery('english', :q)
            ORDER BY ts_rank(tsv, websearch_to_tsquery('english', :q)) DESC
            LIMIT :n
        """)
        async with self.session_factory() as session:
            rows = (await session.execute(stmt, {"q": query, "n": k * 3})).fetchall()
            return await self._checks_for_claims(session, [r.id for r in rows], k)

    async def _checks_for_claims(self, session: AsyncSession, claim_ids: list[int], k: int) -> list[StoredCheck]:
        """For each claim pick its best verdict (prefer one that had evidence, then the newest),
        then return the whole check each verdict belongs to, in claim order, deduplicated."""
        if not claim_ids:
            return []
        stmt = text("""
            SELECT DISTINCT ON (claim_id) claim_id, check_id
            FROM verdicts
            WHERE claim_id IN :ids
            ORDER BY claim_id, (evidence_origin = 'none') ASC, created_at DESC, id DESC
        """).bindparams(bindparam("ids", expanding=True))
        best = {r.claim_id: r.check_id for r in (await session.execute(stmt, {"ids": claim_ids})).fetchall()}
        ordered: list[str] = []
        for cid in claim_ids:
            check_id = best.get(cid)
            if check_id and check_id not in ordered:
                ordered.append(check_id)
        return await self._build_checks(session, ordered[:k])

    async def _build_checks(self, session: AsyncSession, check_ids: list[str]) -> list[StoredCheck]:
        """Rebuild StoredCheck/Card objects from verdict and media rows, preserving input order."""
        if not check_ids:
            return []
        verdict_stmt = text("""
            SELECT v.check_id, c.claim_text, v.label, v.explanation, v.sources,
                   v.disputed_spans, v.evidence_origin, v.persuasion, v.created_at
            FROM verdicts v JOIN claims c ON c.id = v.claim_id
            WHERE v.check_id IN :ids
            ORDER BY v.id
        """).bindparams(bindparam("ids", expanding=True))
        media_stmt = text("""
            SELECT check_id, caption, phash, origin, persuasion, created_at
            FROM media WHERE check_id IN :ids
        """).bindparams(bindparam("ids", expanding=True))

        verdicts: dict[str, list[Any]] = {}
        for r in (await session.execute(verdict_stmt, {"ids": check_ids})).fetchall():
            verdicts.setdefault(r.check_id, []).append(r)
        media = {r.check_id: r for r in (await session.execute(media_stmt, {"ids": check_ids})).fetchall()}

        out: list[StoredCheck] = []
        for cid in check_ids:
            vs, m = verdicts.get(cid, []), media.get(cid)
            if not vs and m is None:
                continue
            claims = [
                ClaimResult.model_validate(
                    {
                        "claim": v.claim_text,
                        "label": v.label,
                        "explanation": v.explanation,
                        "sources": _j(v.sources, []),
                        "disputed_spans": _j(v.disputed_spans, []),
                        "evidence_origin": v.evidence_origin,
                    }
                )
                for v in vs
            ]
            tactics = _j(vs[0].persuasion, []) if vs else _j(m.persuasion, [])
            created = min([v.created_at for v in vs] + ([m.created_at] if m else []))
            card = Card(
                check_id=cid,
                claims=claims,
                origin=OriginResult.model_validate(_j(m.origin, {})) if m else OriginResult(),
                persuasion=[Tactic.model_validate(t) for t in tactics],
                created_at=created,
            )
            out.append(
                StoredCheck(
                    check_id=cid,
                    caption=m.caption if m else None,
                    claims=[c.claim for c in claims],
                    phash=m.phash if m else None,
                    card=card,
                )
            )
        return out

    # ------------------------------------------------------------------ write

    async def save(self, post: Post, card: Card, phash: str | None) -> None:
        """Persist one check. Saving the same check_id again replaces its verdicts and media."""
        embeddings = [await self.encoder.encode(c.claim) for c in card.claims]  # before the transaction
        file_hash = hashlib.sha256(post.image).hexdigest() if post.image else None
        persuasion = json.dumps([t.model_dump(mode="json") for t in card.persuasion])

        async with self.session_factory() as session, session.begin():
            p = {"id": card.check_id}
            await session.execute(text("DELETE FROM verdicts WHERE check_id = :id"), p)
            await session.execute(text("DELETE FROM media WHERE check_id = :id"), p)  # cascades media_claims

            claim_ids: list[int] = []
            for c, emb in zip(card.claims, embeddings, strict=True):
                claim_id = (
                    await session.execute(
                        text("""
                            INSERT INTO claims (claim_text, claim_norm, embedding)
                            VALUES (:claim_text, :claim_norm, CAST(:embedding AS vector))
                            ON CONFLICT (claim_norm) DO UPDATE SET last_seen = now()
                            RETURNING id
                        """),
                        {"claim_text": c.claim, "claim_norm": _norm(c.claim), "embedding": _vec(emb)},
                    )
                ).scalar_one()
                claim_ids.append(claim_id)
                await session.execute(
                    text("""
                        INSERT INTO verdicts (claim_id, check_id, label, explanation, sources,
                                              disputed_spans, evidence_origin, persuasion)
                        VALUES (:claim_id, :check_id, :label, :explanation, CAST(:sources AS jsonb),
                                CAST(:spans AS jsonb), :evidence_origin, CAST(:persuasion AS jsonb))
                    """),
                    {
                        "claim_id": claim_id,
                        "check_id": card.check_id,
                        "label": c.label,
                        "explanation": c.explanation,
                        "sources": json.dumps([s.model_dump(mode="json") for s in c.sources]),
                        "spans": json.dumps(c.disputed_spans),
                        "evidence_origin": c.evidence_origin,
                        "persuasion": persuasion,
                    },
                )

            if post.image or phash:
                media_id = (
                    await session.execute(
                        text("""
                            INSERT INTO media (check_id, phash, file_hash, caption, origin, persuasion)
                            VALUES (:check_id, :phash, :file_hash, :caption,
                                    CAST(:origin AS jsonb), CAST(:persuasion AS jsonb))
                            RETURNING id
                        """),
                        {
                            "check_id": card.check_id,
                            "phash": phash,
                            "file_hash": file_hash,
                            "caption": post.caption,
                            "origin": json.dumps(card.origin.model_dump(mode="json")),
                            "persuasion": persuasion,
                        },
                    )
                ).scalar_one()
                for claim_id in set(claim_ids):
                    await session.execute(
                        text("INSERT INTO media_claims (media_id, claim_id) VALUES (:m, :c)"),
                        {"m": media_id, "c": claim_id},
                    )
