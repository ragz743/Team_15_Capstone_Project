"""PostgreSQL conversations with owner-scoped access and idempotent turns."""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID, uuid4

import psycopg
from backend.chat_turn import PreparedChatTurn
from backend.conversation_context import ConversationContext
from backend.databases.pgvector import PgVectorConnection
from backend.history_search import history_search
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class ConversationNotFoundError(Exception):
    """The requested conversation is not available to this owner."""


class TurnConflictError(Exception):
    """A concurrent request or changed retry cannot be accepted."""


@dataclass(frozen=True)
class AcceptedTurn:
    """A committed user message and the context needed outside the transaction."""

    attempt_id: UUID
    context: ConversationContext
    completed: dict | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    prepared: PreparedChatTurn | None = None


def _connect() -> psycopg.Connection:
    return PgVectorConnection(connect_timeout=5).conn


class ConversationStore:
    """Use short independent transactions, never a shared model-call transaction."""

    def __init__(self, connect: Callable[[], psycopg.Connection] = _connect):
        """Allow an isolated database connection factory in integration tests."""
        self._connect = connect

    @contextmanager
    def _cursor(self, *, read_only: bool = False):
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            if read_only:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            yield cursor

    def owner(self, token: str | None) -> UUID | None:
        """Only a previously issued opaque token establishes ownership."""
        if not token or len(token) != 43:
            return None
        with self._cursor() as cur:
            cur.execute(
                "SELECT id FROM browser_owners WHERE token_hash = %s AND expires_at > now()",
                (sha256(token.encode()).hexdigest(),),
            )
            row = cur.fetchone()
            return row["id"] if row else None

    def create_owner(self) -> tuple[UUID, str]:
        """Store a hash of the random browser credential."""
        owner_id, token = uuid4(), token_urlsafe(32)
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO browser_owners (id, token_hash) VALUES (%s, %s)",
                (owner_id, sha256(token.encode()).hexdigest()),
            )
        return owner_id, token

    def create(self, owner: UUID) -> dict:
        """Start an empty conversation for this browser."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (id, owner_id) VALUES (%s, %s) RETURNING id, title, created_at, updated_at",
                (uuid4(), owner),
            )
            row = cur.fetchone()
            assert row is not None
            return row

    def list_conversations(
        self, owner: UUID, *, before: datetime | None = None, before_id: UUID | None = None
    ) -> list[dict]:
        """Return the 50 most recently changed conversations owned by this browser."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE owner_id = %s AND (%s::timestamptz IS NULL OR (updated_at, id) < (%s, %s::uuid)) "
                "ORDER BY updated_at DESC, id DESC LIMIT 50",
                (owner, before, before, before_id),
            )
            return cur.fetchall()

    def get(self, owner: UUID, conversation: UUID, *, before: int | None = None) -> dict:
        """Load context and at most 40 ordered turns from the same database snapshot."""
        with self._cursor(read_only=True) as cur:
            cur.execute(
                "SELECT id, title, created_at, updated_at, context FROM conversations WHERE id = %s AND owner_id = %s",
                (conversation, owner),
            )
            result = cur.fetchone()
            if result is None:
                raise ConversationNotFoundError
            cur.execute(
                "SELECT t.* FROM conversation_turns t JOIN conversations c ON c.id = t.conversation_id "
                "WHERE c.id = %s AND c.owner_id = %s AND (%s::integer IS NULL OR t.ordinal < %s) "
                "ORDER BY t.ordinal DESC LIMIT 41",
                (conversation, owner, before, before),
            )
            rows = cur.fetchall()
            result["next_before"] = rows[39]["ordinal"] if len(rows) > 40 else None
            result["context"] = ConversationContext.model_validate(result["context"]).model_dump(mode="json")
            result["messages"] = [message for row in reversed(rows[:40]) for message in _messages(row)]
            return result

    def begin(
        self, owner: UUID, conversation: UUID, request: UUID, content: str, *, request_input: dict | None = None
    ) -> AcceptedTurn:
        """Commit one user turn, or return its existing completed result on retry."""
        attempt = uuid4()
        request_input = request_input or {}
        with self._cursor() as cur:
            cur.execute("SELECT * FROM conversations WHERE id = %s AND owner_id = %s FOR UPDATE", (conversation, owner))
            chat = cur.fetchone()
            if chat is None:
                raise ConversationNotFoundError
            cur.execute(
                "SELECT *, lease_until > now() AS active FROM conversation_turns "
                "WHERE conversation_id = %s ORDER BY ordinal DESC LIMIT 1",
                (conversation,),
            )
            latest = cur.fetchone()
            cur.execute(
                "SELECT * FROM conversation_turns WHERE conversation_id = %s AND request_id = %s",
                (conversation, request),
            )
            existing = cur.fetchone()
            if existing:
                _validate_retry(existing, latest, content, request_input, request)
                if existing["status"] == "completed":
                    return _completed_turn(existing)
            if latest and latest["status"] == "pending" and latest["active"]:
                raise TurnConflictError("This conversation is still processing a message. Please try again shortly.")
            cur.execute(
                "UPDATE conversation_turns SET status = 'failed' WHERE conversation_id = %s AND status = 'pending'",
                (conversation,),
            )
            if existing:
                requested_at = _retry_turn(cur, existing, attempt)
            else:
                requested_at = _insert_turn(cur, chat, request, attempt, content, request_input)
            return AcceptedTurn(
                attempt,
                ConversationContext.model_validate(chat["context"]),
                requested_at=requested_at,
                prepared=PreparedChatTurn.model_validate(existing["prepared_turn"])
                if existing and existing["prepared_turn"] is not None
                else None,
            )

    def prepare(self, owner: UUID, conversation: UUID, request: UUID, attempt: UUID, turn: PreparedChatTurn) -> None:
        """Persist resolved input once, only while this attempt owns the turn."""
        snapshot = turn.model_dump(mode="json")
        with self._cursor() as cur:
            cur.execute(
                "SELECT id FROM conversations WHERE id = %s AND owner_id = %s FOR UPDATE", (conversation, owner)
            )
            if not cur.fetchone():
                raise ConversationNotFoundError
            cur.execute(
                "UPDATE conversation_turns SET prepared_turn = %s "
                "WHERE conversation_id = %s AND request_id = %s AND attempt_id = %s AND status = 'pending' "
                "AND (prepared_turn IS NULL OR prepared_turn = %s) RETURNING request_id",
                (Jsonb(snapshot), conversation, request, attempt, Jsonb(snapshot)),
            )
            if not cur.fetchone():
                raise TurnConflictError(
                    "This request was superseded or its resolved inputs changed. Reload the conversation."
                )

    def complete(
        self,
        owner: UUID,
        conversation: UUID,
        request: UUID,
        attempt: UUID,
        reply: str,
        model: str,
        context: ConversationContext,
        *,
        metadata: dict | None = None,
    ) -> None:
        """Publish an answer only if this attempt still owns the pending turn."""
        if not reply.strip():
            raise ValueError("Empty assistant answer")
        with self._cursor() as cur:
            cur.execute(
                "SELECT id FROM conversations WHERE id = %s AND owner_id = %s FOR UPDATE", (conversation, owner)
            )
            if not cur.fetchone():
                raise ConversationNotFoundError
            cur.execute(
                "UPDATE conversation_turns SET status = 'completed', assistant_content = %s, "
                "completed_at = now(), model = %s, context = %s, result_metadata = %s "
                "WHERE conversation_id = %s AND request_id = %s AND attempt_id = %s "
                "AND status = 'pending' RETURNING ordinal",
                (
                    reply,
                    model,
                    Jsonb(context.model_dump(mode="json")),
                    Jsonb(metadata or {}),
                    conversation,
                    request,
                    attempt,
                ),
            )
            if not cur.fetchone():
                raise TurnConflictError("This request was superseded. Reload the conversation.")
            cur.execute(
                "UPDATE conversations SET context = %s, updated_at = now() WHERE id = %s AND owner_id = %s",
                (Jsonb(context.model_dump(mode="json")), conversation, owner),
            )

    def fail(self, owner: UUID, conversation: UUID, request: UUID, attempt: UUID) -> None:
        """Keep the accepted question while recording that no answer was produced."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE conversation_turns t SET status = 'failed' FROM conversations c "
                "WHERE c.id = t.conversation_id AND c.owner_id = %s AND c.id = %s "
                "AND t.request_id = %s AND t.attempt_id = %s AND t.status = 'pending'",
                (owner, conversation, request, attempt),
            )

    def history_window(self, owner: UUID, conversation: UUID, *, before: datetime) -> list[dict]:
        """Provide six earlier turns for interpretation, excluding future replies and other owners."""
        with self._cursor() as cur:
            cur.execute("SELECT id FROM conversations WHERE id = %s AND owner_id = %s", (conversation, owner))
            if not cur.fetchone():
                raise ConversationNotFoundError
            cur.execute(
                "SELECT t.user_content, t.requested_at, "
                "CASE WHEN t.completed_at <= %s THEN t.assistant_content END AS answer "
                "FROM conversation_turns t JOIN conversations c ON c.id = t.conversation_id "
                "WHERE c.owner_id = %s AND c.id = %s AND t.requested_at < %s "
                "ORDER BY t.ordinal DESC LIMIT 6",
                (before, owner, conversation, before),
            )
            return [
                {
                    "user": row["user_content"][:1200],
                    "assistant": (row["answer"] or "")[:2000],
                    "asked_at": row["requested_at"].isoformat(),
                }
                for row in reversed(cur.fetchall())
            ]

    def search_history(
        self,
        owner: UUID,
        conversation: UUID,
        *,
        before: datetime,
        scope: str,
        terms: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict]:
        """Search literal topic alternatives within owned messages as they existed at acceptance."""
        if scope not in {"all", "current", "previous"} or len(terms) > 8:
            raise ValueError("Invalid history search scope")
        if any(not term.strip() or len(term) > 80 for term in terms):
            raise ValueError("Invalid history search term")
        with self._cursor() as cur:
            cur.execute("SELECT id FROM conversations WHERE id = %s AND owner_id = %s", (conversation, owner))
            if not cur.fetchone():
                raise ConversationNotFoundError
            target = conversation if scope == "current" else None
            if scope == "previous":
                target = _previous_conversation(cur, owner, conversation, before)
                if target is None:
                    return []
            query, parameters = history_search(owner, before, target=target, terms=terms, start=start, end=end)
            cur.execute(query, parameters)
            return cur.fetchall()


def _messages(row: dict) -> list[dict]:
    messages = [
        {
            "id": f"{row['request_id']}:user",
            "request_id": row["request_id"],
            "role": "user",
            "content": row["user_content"],
            "created_at": row["requested_at"],
            "status": row["status"],
            "request_input": row["request_input"],
        }
    ]
    if row["status"] == "completed":
        messages.append(
            {
                "id": f"{row['request_id']}:assistant",
                "request_id": row["request_id"],
                "role": "assistant",
                "content": row["assistant_content"],
                "created_at": row["completed_at"],
                "status": "completed",
                "metadata": row["result_metadata"],
            }
        )
    return messages


def _validate_retry(existing, latest, content, request_input, request):
    if existing["user_content"] != content or existing["request_input"] != request_input:
        raise TurnConflictError("A retry must contain the original message and map point.")
    if existing["status"] != "completed" and latest["request_id"] != request:
        raise TurnConflictError("This failed turn has newer messages. Send a new question instead.")


def _completed_turn(row: dict) -> AcceptedTurn:
    return AcceptedTurn(
        row["attempt_id"],
        ConversationContext.model_validate(row["context"]),
        {"reply": row["assistant_content"], "model": row["model"], **row["result_metadata"]},
        requested_at=row["requested_at"],
    )


def _previous_conversation(cur, owner: UUID, conversation: UUID, before: datetime) -> UUID | None:
    cur.execute(
        "SELECT c.id FROM conversations c JOIN LATERAL ("
        "SELECT requested_at, ordinal FROM conversation_turns WHERE conversation_id = c.id AND requested_at < %s "
        "ORDER BY requested_at DESC, ordinal DESC LIMIT 1) last_turn ON true "
        "WHERE c.owner_id = %s AND c.id <> %s "
        "ORDER BY last_turn.requested_at DESC, c.id DESC, last_turn.ordinal DESC LIMIT 1",
        (before, owner, conversation),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def _retry_turn(cur, existing: dict, attempt: UUID) -> datetime:
    cur.execute(
        "UPDATE conversation_turns SET status = 'pending', attempt_id = %s, "
        "lease_until = now() + INTERVAL '2 minutes' WHERE conversation_id = %s AND request_id = %s",
        (attempt, existing["conversation_id"], existing["request_id"]),
    )
    return existing["requested_at"]


def _insert_turn(cur, chat: dict, request: UUID, attempt: UUID, content: str, request_input: dict) -> datetime:
    cur.execute(
        "INSERT INTO conversation_turns "
        "(conversation_id, request_id, ordinal, user_content, status, attempt_id, lease_until, request_input) "
        "VALUES (%s, %s, %s, %s, 'pending', %s, now() + INTERVAL '2 minutes', %s) RETURNING requested_at",
        (chat["id"], request, chat["next_ordinal"], content, attempt, Jsonb(request_input)),
    )
    inserted = cur.fetchone()
    assert inserted is not None
    cur.execute(
        "UPDATE conversations SET next_ordinal = next_ordinal + 1, updated_at = now(), "
        "title = CASE WHEN next_ordinal = 1 THEN %s ELSE title END WHERE id = %s AND owner_id = %s",
        (content[:80], chat["id"], chat["owner_id"]),
    )
    return inserted["requested_at"]
