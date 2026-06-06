from sqlalchemy.orm import Session
from app import models
from app.rag.chat import ask_question


def ask_chatbot(db: Session, user_id: str, question: str) -> dict:
    result = ask_question(question)

    record = models.ChatHistory(
        user_id=user_id,
        question=question,
        answer=result.get('answer', ''),
        confidence=result.get('confidence'),
        source_documents={'sources': result.get('sources', [])},
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        'id': record.id,
        'question': question,
        'answer': result.get('answer', ''),
        'confidence': result.get('confidence'),
        'sources': result.get('sources', []),
        'chat_model': result.get('chat_model'),
        'embeddings_model': result.get('embeddings_model'),
        'created_at': record.created_at,
    }


def get_user_chat_history(db: Session, user_id: str, limit: int = 50) -> dict:
    history = (
        db.query(models.ChatHistory)
        .filter(models.ChatHistory.user_id == user_id)
        .order_by(models.ChatHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    return {'history': history, 'total_count': len(history)}
