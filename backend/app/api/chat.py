"""
Chat API routes — send messages, manage sessions, view history.
"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.models import (
    ChatRequest, ChatResponse, ChatMessage, ChatSession,
    ChatSessionDetail, SourceReference, ConfidenceInfo,
)

router = APIRouter(prefix="/api/chat", tags=["Chat"])


def _sse(obj: dict) -> str:
    """Format a dict as a Server-Sent Events `data:` frame."""
    return f"data: {json.dumps(obj)}\n\n"


def get_deps():
    """Lazy import to avoid circular imports at module load time."""
    from app.main import get_query_engine, get_sqlite
    return get_query_engine(), get_sqlite()


# -------------------------------------------------------------------------
# POST /api/chat — send a message and get an AI response
# -------------------------------------------------------------------------
@router.post("", response_model=ChatResponse)
async def send_message(req: ChatRequest):
    """Send a chat message and receive an AI-generated response with sources."""
    query_engine, db = get_deps()

    # Create or validate session
    if req.session_id:
        if not db.session_exists(req.session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        session_id = req.session_id
    else:
        session_id = db.create_session()

    # Save the user message
    db.add_message(session_id, "user", req.user_message)

    # Load chat history for context
    history_rows = db.get_session_messages(session_id)
    # Convert to the format the QueryEngine expects (exclude the message we just added)
    chat_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history_rows[:-1]  # Exclude the latest user message — it's the current query
    ]

    # Run the retrieval + generation pipeline
    result = query_engine.query(
        user_message=req.user_message,
        chat_history=chat_history if chat_history else None,
        attachments=req.attachments or None,
    )

    # Save the assistant response (persist enough to rebuild the UI on reload)
    sources_for_db = [
        {
            "file_path": s.get("file_path", ""),
            "file_type": s.get("file_type", ""),
            "chunk_text": s.get("chunk_text", ""),
            "relevance_score": s.get("relevance_score", 0.0),
            "cited": s.get("cited", False),
        }
        for s in result.get("sources", [])
    ]
    db.add_message(session_id, "assistant", result["answer"], sources_for_db)

    # Build response
    return ChatResponse(
        answer=result["answer"],
        sources=[SourceReference(**s) for s in result.get("sources", [])],
        session_id=session_id,
        entities_referenced=result.get("entities_referenced", []),
        confidence=ConfidenceInfo(**result.get("confidence", {})),
    )


# -------------------------------------------------------------------------
# POST /api/chat/stream — same as /api/chat, but streams tokens over SSE
# -------------------------------------------------------------------------
@router.post("/stream")
async def send_message_stream(req: ChatRequest):
    """Stream an AI response token-by-token as Server-Sent Events.

    Event frames (JSON in each SSE `data:`):
        {"type": "session", "session_id": "..."}      once, first
        {"type": "token", "text": "..."}              repeated
        {"type": "done", "answer", "sources",         once, at the end
         "entities_referenced", "confidence"}
        {"type": "error", "detail": "..."}            on failure
    """
    query_engine, db = get_deps()

    # Create or validate session
    if req.session_id:
        if not db.session_exists(req.session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        session_id = req.session_id
    else:
        session_id = db.create_session()

    # Save the user message
    db.add_message(session_id, "user", req.user_message)

    # Load history for context (exclude the message we just added)
    history_rows = db.get_session_messages(session_id)
    chat_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history_rows[:-1]
    ]

    def event_stream():
        yield _sse({"type": "session", "session_id": session_id})
        try:
            for ev in query_engine.query_stream(
                user_message=req.user_message,
                chat_history=chat_history if chat_history else None,
                attachments=req.attachments or None,
            ):
                if ev.get("type") == "token":
                    yield _sse({"type": "token", "text": ev["text"]})
                elif ev.get("type") == "done":
                    # Persist the assistant turn (same shape as /api/chat).
                    sources_for_db = [
                        {
                            "file_path": s.get("file_path", ""),
                            "file_type": s.get("file_type", ""),
                            "chunk_text": s.get("chunk_text", ""),
                            "relevance_score": s.get("relevance_score", 0.0),
                            "cited": s.get("cited", False),
                        }
                        for s in ev.get("sources", [])
                    ]
                    db.add_message(session_id, "assistant", ev["answer"], sources_for_db)
                    yield _sse({
                        "type": "done",
                        "answer": ev["answer"],
                        "sources": sources_for_db,
                        "entities_referenced": ev.get("entities_referenced", []),
                        "confidence": ev.get("confidence", {}),
                    })
        except Exception as e:  # noqa: BLE001 — surface any failure to the client
            print(f"[chat/stream] Error: {e}")
            yield _sse({"type": "error", "detail": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )


# -------------------------------------------------------------------------
# GET /api/chat/sessions — list all chat sessions
# -------------------------------------------------------------------------
@router.get("/sessions", response_model=list[ChatSession])
async def list_sessions():
    """List all chat sessions, most recent first."""
    _, db = get_deps()
    rows = db.list_sessions()
    return [
        ChatSession(
            id=r["id"],
            title=r["title"],
            created_at=r["created_at"],
            last_message_at=r["last_message_at"],
            message_count=r.get("message_count", 0),
        )
        for r in rows
    ]


# -------------------------------------------------------------------------
# GET /api/chat/sessions/{session_id} — get full session with messages
# -------------------------------------------------------------------------
@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(session_id: str):
    """Get a full chat session with all messages."""
    _, db = get_deps()

    if not db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Get session info
    sessions = db.list_sessions()
    session_info = next((s for s in sessions if s["id"] == session_id), None)
    if not session_info:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get messages
    messages = db.get_session_messages(session_id)

    return ChatSessionDetail(
        session=ChatSession(
            id=session_info["id"],
            title=session_info["title"],
            created_at=session_info["created_at"],
            last_message_at=session_info["last_message_at"],
            message_count=session_info.get("message_count", 0),
        ),
        messages=[
            ChatMessage(
                role=m["role"],
                content=m["content"],
                sources=[SourceReference(**s) for s in m.get("sources", [])],
                timestamp=m["timestamp"],
            )
            for m in messages
        ],
    )


# -------------------------------------------------------------------------
# DELETE /api/chat/sessions/{session_id} — delete a session
# -------------------------------------------------------------------------
@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session and all its messages."""
    _, db = get_deps()

    if not db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    db.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}
