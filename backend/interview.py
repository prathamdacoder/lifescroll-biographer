"""The 15-minute guided interview: a fixed spine plus AI follow-ups."""
from . import groq_client

SPINE = [
    {"id": "origin", "minutes": 1,
     "q": "Let's start at the beginning. Where and when were you born, and who was in the house with you?"},
    {"id": "childhood", "minutes": 2,
     "q": "Describe one ordinary day from your childhood — the smells, the sounds, what you were doing."},
    {"id": "family", "minutes": 2,
     "q": "Tell me about the person who shaped you most in those early years. What did they say and do?"},
    {"id": "school", "minutes": 1,
     "q": "What were you like at school, and when did you first feel like yourself?"},
    {"id": "leaving", "minutes": 2,
     "q": "What was the first big leap you took away from home, and how did it feel?"},
    {"id": "work", "minutes": 2,
     "q": "Walk me through your working life — how it started, what you were proud of, what you'd change."},
    {"id": "love", "minutes": 2,
     "q": "Tell me about love: meeting, choosing, losing, or staying. What happened?"},
    {"id": "hard", "minutes": 2,
     "q": "What was the hardest stretch of your life, and how did you get through it?"},
    {"id": "joy", "minutes": 1,
     "q": "What's a moment of pure happiness you'd live again exactly as it was?"},
    {"id": "change", "minutes": 1,
     "q": "How did you change in your middle years? What did you finally let go of?"},
    {"id": "people", "minutes": 1,
     "q": "Who are the people that made your life what it is, and what do you owe them?"},
    {"id": "legacy", "minutes": 1,
     "q": "If someone reads this book in fifty years, what do you want them to know about you?"},
]


def spine() -> list:
    return [{"id": s["id"], "question": s["q"], "minutes": s["minutes"]} for s in SPINE]


def follow_up(question: str, answer: str, asked: list) -> dict:
    """One warm follow-up that digs for a concrete scene; falls back offline."""
    words = len((answer or "").split())
    if words < 12:
        return {"question": "Can you say a bit more about that? Even a small detail helps — "
                            "what did you see, or who was there?", "source": "rule"}
    if not groq_client.available():
        return {"question": "What's one specific moment from that you still picture clearly?",
                "source": "rule"}
    try:
        data = groq_client.chat_json([
            {"role": "system", "content":
             "You are a gentle, curious oral-history interviewer. You ask ONE short "
             "follow-up question (max 25 words) that pulls out a concrete scene: a "
             "place, a person, a sensory detail, or what was said out loud."},
            {"role": "user", "content":
             f"Question asked: {question}\nTheir answer: \"\"\"{answer[:4000]}\"\"\"\n"
             f"Already asked: {asked[-5:]}\n\n"
             'Return STRICT JSON: {"question": "...", "why": "..."}'}],
            temperature=0.8, max_tokens=300)
        q = (data.get("question") or "").strip()
        return {"question": q or "What happened next?", "source": "ai"}
    except Exception:
        return {"question": "What happened right after that?", "source": "rule"}


def transcript_from(answers: list) -> str:
    """answers: [{question, answer}] -> a clean interview transcript."""
    parts = []
    for item in answers:
        q = (item.get("question") or "").strip()
        a = (item.get("answer") or "").strip()
        if a:
            parts.append(f"INTERVIEWER: {q}\nSUBJECT: {a}")
    return "\n\n".join(parts)
