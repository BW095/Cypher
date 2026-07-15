"""
Chat API routes — send messages, manage sessions, view history.
"""

from fastapi import APIRouter, HTTPException

from app.api.models import (
    ChatRequest, ChatResponse, ChatMessage, ChatSession,
    ChatSessionDetail, SourceReference,
)

router = APIRouter(prefix="/api/chat", tags=["Chat"])


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
    )

    # Save the assistant response
    sources_for_db = [
        {"file_path": s["file_path"], "file_type": s["file_type"], "relevance_score": s["relevance_score"]}
        for s in result.get("sources", [])
    ]
    db.add_message(session_id, "assistant", result["answer"], sources_for_db)

    # Build response
    return ChatResponse(
        answer=result["answer"],
        sources=[SourceReference(**s) for s in result.get("sources", [])],
        session_id=session_id,
        entities_referenced=result.get("entities_referenced", []),
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
