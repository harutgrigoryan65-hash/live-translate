import json
import math
import os
import re
import time

from google import genai


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_PATH = os.path.join(BASE_DIR, "knowledge_base.json")
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"


WORD_RE = re.compile(r"[A-Za-zА-Яа-я0-9_+#.-]{2,}")
STOP_WORDS = {
    "the", "and", "for", "you", "your", "are", "was", "were", "with", "that",
    "this", "from", "have", "has", "had", "what", "why", "how", "when", "where",
    "who", "which", "about", "tell", "me", "my", "our", "their", "they", "them",
    "как", "что", "это", "для", "или", "если", "меня", "мне", "мой", "моя",
    "мои", "про", "при", "где", "когда", "почему", "какой", "какая", "какие",
}


def load_knowledge():
    if not os.path.exists(KNOWLEDGE_PATH):
        return {"version": 1, "sources": [], "chunks": []}
    try:
        with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "sources": [], "chunks": []}
    data.setdefault("version", 1)
    data.setdefault("sources", [])
    data.setdefault("chunks", [])
    return data


def save_knowledge(data):
    with open(KNOWLEDGE_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def read_text_file(path):
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as file:
                return file.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as file:
        return file.read()


def normalize_text(text):
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text):
    words = [word.lower() for word in WORD_RE.findall(text or "")]
    return [word for word in words if word not in STOP_WORDS and len(word) > 1]


def embedding_prompt(text, kind):
    if kind == "query":
        return (
            "Represent this interview question for retrieving relevant personal "
            "experience, portfolio, resume, and life-history facts.\n\nQuery:\n"
            + normalize_text(text)
        )
    return (
        "Represent this personal knowledge-base document chunk for retrieval. "
        "It may contain resume facts, portfolio projects, work experience, "
        "life history, achievements, skills, and interview answer material.\n\n"
        "Document chunk:\n"
        + normalize_text(text)
    )


def extract_embedding(response):
    embeddings = getattr(response, "embeddings", None)
    if embeddings:
        first = embeddings[0]
        values = getattr(first, "values", None)
        if values is not None:
            return [float(value) for value in values]
        if isinstance(first, dict) and "values" in first:
            return [float(value) for value in first["values"]]

    embedding = getattr(response, "embedding", None)
    if embedding:
        values = getattr(embedding, "values", None)
        if values is not None:
            return [float(value) for value in values]
    raise RuntimeError("Gemini embedding response did not contain vector values.")


def embed_text(api_key, text, model=DEFAULT_EMBEDDING_MODEL, kind="document"):
    if not api_key:
        raise RuntimeError("Google API key нужен для embeddings.")
    client = genai.Client(api_key=api_key)
    response = client.models.embed_content(
        model=model,
        contents=embedding_prompt(text, kind),
    )
    return extract_embedding(response)


def cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def chunk_text(text, max_chars=1200, overlap=160):
    text = normalize_text(text)
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if boundary > start + max_chars * 0.55:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def add_text_file(path, api_key=None, embedding_model=DEFAULT_EMBEDDING_MODEL, status_callback=None):
    text = read_text_file(path)
    chunks = chunk_text(text)
    data = load_knowledge()
    source_id = f"src-{int(time.time() * 1000)}"
    source = {
        "id": source_id,
        "name": os.path.basename(path),
        "path": os.path.abspath(path),
        "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chars": len(text),
        "chunks": len(chunks),
        "embedding_model": embedding_model,
    }
    data["sources"].append(source)
    for index, chunk in enumerate(chunks):
        if status_callback:
            status_callback(index + 1, len(chunks))
        embedding = embed_text(api_key, chunk, model=embedding_model, kind="document")
        data["chunks"].append(
            {
                "source_id": source_id,
                "source_name": source["name"],
                "index": index,
                "text": chunk,
                "tokens": tokenize(chunk),
                "embedding": embedding,
                "embedding_model": embedding_model,
            }
        )
    save_knowledge(data)
    return source


def rebuild_embeddings(api_key=None, embedding_model=DEFAULT_EMBEDDING_MODEL, status_callback=None):
    data = load_knowledge()
    chunks = data["chunks"]
    for index, chunk in enumerate(chunks):
        if status_callback:
            status_callback(index + 1, len(chunks))
        chunk["embedding"] = embed_text(
            api_key,
            chunk.get("text", ""),
            model=embedding_model,
            kind="document",
        )
        chunk["embedding_model"] = embedding_model
    for source in data["sources"]:
        source["embedding_model"] = embedding_model
    save_knowledge(data)
    return data


def clear_knowledge():
    data = {"version": 1, "sources": [], "chunks": []}
    save_knowledge(data)
    return data


def knowledge_stats():
    data = load_knowledge()
    chars = sum(source.get("chars", 0) for source in data["sources"])
    embedded = sum(1 for chunk in data["chunks"] if chunk.get("embedding"))
    return {
        "sources": len(data["sources"]),
        "chunks": len(data["chunks"]),
        "embedded_chunks": embedded,
        "chars": chars,
        "path": KNOWLEDGE_PATH,
    }


def retrieve_context(
    query,
    api_key=None,
    embedding_model=DEFAULT_EMBEDDING_MODEL,
    limit=5,
    min_similarity=0.42,
):
    data = load_knowledge()
    chunks_with_embeddings = [
        chunk for chunk in data["chunks"]
        if chunk.get("embedding") and chunk.get("embedding_model") == embedding_model
    ]
    if not query.strip() or not chunks_with_embeddings:
        return "", []

    query_embedding = embed_text(api_key, query, model=embedding_model, kind="query")
    scored = []
    for chunk in chunks_with_embeddings:
        score = cosine_similarity(query_embedding, chunk.get("embedding"))
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = []
    for score, chunk in scored[:limit]:
        if score < min_similarity:
            continue
        enriched = dict(chunk)
        enriched["score"] = score
        selected.append(enriched)
    context_parts = []
    for chunk in selected:
        context_parts.append(
            f"Source: {chunk.get('source_name')} #{chunk.get('index', 0) + 1} "
            f"(similarity: {chunk.get('score', 0):.3f})\n{chunk.get('text', '')}"
        )
    return "\n\n".join(context_parts), selected
