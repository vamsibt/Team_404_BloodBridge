# app/routers/chatbot.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.deps import get_current_user
from app.database import get_db
from app.services.chatbot_service import ask_chatbot, get_user_chat_history

router = APIRouter()


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    language: str = 'en'


@router.post('/chat')
async def chat_with_bot(
    body: ChatMessage,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        result = ask_chatbot(db, current_user.id, body.message)
    except Exception as exc:
        raise HTTPException(503, f'Chatbot service unavailable: {exc}') from exc

    return {
        'reply': result['answer'],
        'confidence': result['confidence'],
        'sources': result['sources'],
        'language': body.language,
        'user_id': current_user.id,
        'chat_model': result.get('chat_model'),
        'created_at': result.get('created_at'),
    }


@router.get('/history')
def get_chat_history(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return get_user_chat_history(db, current_user.id)
