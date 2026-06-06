import os
from functools import lru_cache

from sklearn.metrics.pairwise import cosine_similarity
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from groq import Groq

from app.config import settings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAISS_DIR = os.path.join(BASE_DIR, settings.FAISS_INDEX_PATH.lstrip('./'))

_client = None


def get_groq_client():
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


@lru_cache(maxsize=1)
def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name=settings.EMBEDDINGS_MODEL,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True},
    )


def load_vectorstore():
    embeddings = get_embeddings()
    return FAISS.load_local(
        FAISS_DIR,
        embeddings,
        allow_dangerous_deserialization=True,
    )


def calculate_similarity(query, document_text):
    embeddings = get_embeddings()
    query_embedding = embeddings.embed_query(f'Represent this sentence for retrieval: {query}')
    doc_embedding = embeddings.embed_query(document_text)
    similarity = cosine_similarity([query_embedding], [doc_embedding])[0][0]
    return float(round(similarity * 100, 2))


def ask_question(question: str):
    if not settings.GROQ_API_KEY:
        return {
            'answer': 'Chatbot is not configured. Please set GROQ_API_KEY in the environment.',
            'confidence': 0,
            'sources': [],
        }

    vectorstore = load_vectorstore()
    docs_and_scores = vectorstore.similarity_search_with_score(
        f'Represent this sentence for retrieval: {question}',
        k=5,
    )
    filtered_docs = []
    source_details = []

    for doc, score in docs_and_scores:
        score = float(score)
        if score < 1.2:
            filtered_docs.append(doc)
            source = doc.metadata.get('source')
            similarity_confidence = calculate_similarity(question, doc.page_content)
            page = doc.metadata.get('page')
            source_details.append({
                'source': os.path.basename(source) if source else 'unknown',
                'page': page + 1 if page is not None else None,
                'confidence': similarity_confidence,
                'raw_score': float(round(score, 4)),
            })

    if not filtered_docs:
        return {
            'answer': 'I could not find that information in the knowledge base.',
            'confidence': 0,
            'sources': [],
        }

    context = '\n\n'.join([doc.page_content for doc in filtered_docs])
    prompt = f"""
You are BloodBridge Assistant.

Rules:
1. Answer ONLY using the supplied context.
2. Do not use outside knowledge.
3. If the answer is not explicitly present in the context, respond exactly:
   "I could not find that information in the knowledge base."
4. Keep answers concise.
5. Never invent medical information.

CONTEXT:
{context}

QUESTION:
{question}
"""

    client = get_groq_client()
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0,
    )
    answer = response.choices[0].message.content
    overall_confidence = calculate_similarity(question, filtered_docs[0].page_content)

    unique_sources = []
    seen = set()
    for source in source_details:
        if source['source'] not in seen:
            unique_sources.append(source)
            seen.add(source['source'])

    return {
        'answer': answer,
        'confidence': overall_confidence,
        'sources': unique_sources,
        'chat_model': settings.GROQ_MODEL,
        'embeddings_model': settings.EMBEDDINGS_MODEL,
    }
