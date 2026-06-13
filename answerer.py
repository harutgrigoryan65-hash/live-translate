import os

from google import genai
from google.genai import types


QUESTION_STARTS = (
    "what ",
    "why ",
    "how ",
    "when ",
    "where ",
    "who ",
    "which ",
    "can ",
    "could ",
    "should ",
    "would ",
    "do ",
    "does ",
    "did ",
    "is ",
    "are ",
    "am ",
    "will ",
    "как ",
    "что ",
    "почему ",
    "зачем ",
    "когда ",
    "где ",
    "кто ",
    "какой ",
    "какая ",
    "какие ",
    "можно ",
    "можешь ",
    "нужно ",
    "стоит ",
)


def looks_like_question(english_text, russian_text):
    text = f"{english_text or ''} {russian_text or ''}".strip()
    if not text:
        return False
    lowered = text.lower().lstrip()
    return "?" in text or lowered.startswith(QUESTION_STARTS)


def generate_answer(
    *,
    api_key=None,
    model="gemini-2.5-flash",
    english_text="",
    russian_text="",
    recent_context="",
    rag_context="",
    custom_prompt="",
    answer_language="ru",
):
    api_key = api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Google API key не задан для answer model.")

    client = genai.Client(api_key=api_key)
    prompt = f"""
You are a real-time interview and conversation assistant.
The user hears English speech and Russian translation. Answer the latest question directly.

Rules:
- Answer in language code: {answer_language}
- Be concise: 2-5 sentences.
- If the phrase is not a question, say nothing.
- Do not mention that you are an AI or that you saw a transcript.
- If user knowledge is relevant, answer as the user, based on that experience.
- If user knowledge is not enough, give a general but honest answer and do not invent personal facts.

User answer style/prompt:
{custom_prompt.strip() or "-"}

Recent session context:
{recent_context.strip() or "-"}

User knowledge base:
{rag_context.strip() or "-"}

English speech:
{english_text.strip() or "-"}

Russian translation:
{russian_text.strip() or "-"}
""".strip()

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.35,
            max_output_tokens=512,
        ),
    )
    return (response.text or "").strip()
