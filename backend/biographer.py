"""The biography engine: transcript -> structured 50-page book with illustrations."""
import concurrent.futures as futures
import json
import re
import textwrap
import threading
import traceback
from typing import Callable

from . import config, db, groq_client, images

SYSTEM = (
    "You are Lifescroll, an award-winning ghostwriter of literary memoirs. You turn "
    "raw, rambling interview transcripts into warm, vivid, dignified narrative "
    "non-fiction. You never invent hard facts (names, dates, places, jobs) that the "
    "subject did not provide, but you do render scenes with sensory texture, "
    "interiority and pacing. You write in a close, humane third-or-first person "
    "matching the subject's own voice and idioms."
)


# --------------------------------------------------------------------- planning
def build_plan(transcript: str, subject_hint: str = "") -> dict:
    chapters = config.TARGET_CHAPTERS
    prompt = f"""Read this life-story interview transcript and design a {chapters}-chapter memoir.

TRANSCRIPT
\"\"\"{transcript[:24000]}\"\"\"

Return STRICT JSON:
{{
  "title": "evocative book title (max 6 words)",
  "subtitle": "a short subtitle naming the person and arc",
  "narrator": "first" or "third",
  "voice_notes": "2 sentences on tone, idiom and rhythm to imitate",
  "dedication": "one-line dedication in the subject's voice",
  "chapters": [
    {{"number": 1, "title": "chapter title", "era": "life period e.g. 'Childhood, 1970s'",
      "summary": "3-4 sentences of exactly what this chapter covers, grounded ONLY in transcript facts",
      "beats": ["scene beat 1", "scene beat 2", "scene beat 3", "scene beat 4"],
      "emotional_turn": "what shifts for the subject here"}}
  ]
}}

Rules: exactly {chapters} chapters, chronological, no overlap between chapters, and
every chapter must be anchored in something the subject actually said. If the
transcript is thin, spread the material and lean on reflection rather than invention."""
    data = groq_client.chat_json(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": prompt + (f"\n\nSubject: {subject_hint}" if subject_hint else "")}],
        temperature=0.7, max_tokens=4096,
    )
    plan_chapters = data.get("chapters") or []
    for i, ch in enumerate(plan_chapters, start=1):
        ch["number"] = i
        ch.setdefault("title", f"Chapter {i}")
        ch.setdefault("era", "")
        ch.setdefault("summary", "")
        ch.setdefault("beats", [])
    data["chapters"] = plan_chapters[:config.TARGET_CHAPTERS]
    return data


# --------------------------------------------------------------------- chapters
def write_chapter(transcript: str, plan: dict, chapter: dict) -> str:
    """Two passes per chapter so we reliably reach the word budget."""
    half = max(700, config.WORDS_PER_CHAPTER // 2)
    beats = chapter.get("beats") or []
    first_beats = beats[: max(1, len(beats) // 2)] or ["opening scene"]
    second_beats = beats[max(1, len(beats) // 2):] or ["closing reflection"]

    base = f"""BOOK: "{plan.get('title','A Life')}" — {plan.get('subtitle','')}
NARRATION: {plan.get('narrator','first')} person. VOICE: {plan.get('voice_notes','')}
CHAPTER {chapter['number']}: "{chapter['title']}" ({chapter.get('era','')})
CHAPTER BRIEF: {chapter.get('summary','')}
EMOTIONAL TURN: {chapter.get('emotional_turn','')}

SOURCE TRANSCRIPT (the only factual authority):
\"\"\"{transcript[:16000]}\"\"\"
"""
    part1 = groq_client.chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": base + f"""
Write the FIRST HALF of this chapter, covering these beats: {json.dumps(first_beats)}.
- About {half} words of finished literary prose.
- Open with a concrete scene, not a summary.
- Use paragraphs only. No headings, no bullet points, no meta commentary, no "Part 1".
- Do not conclude the chapter; it continues."""}],
        temperature=0.8, max_tokens=4096)

    part2 = groq_client.chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": base + f"""
Here is the first half of the chapter already written:
\"\"\"{part1[-4000:]}\"\"\"

Continue seamlessly and write the SECOND HALF, covering: {json.dumps(second_beats)}.
- About {half} words.
- Do not repeat or summarise what was already written; continue mid-narrative.
- Land the emotional turn and end the chapter with a resonant closing paragraph.
- Paragraphs only, no headings, no meta commentary."""}],
        temperature=0.8, max_tokens=4096)

    return _clean(part1) + "\n\n" + _clean(part2)


def chapter_images(plan: dict, chapter: dict, text: str) -> list:
    n = config.IMAGES_PER_CHAPTER
    try:
        data = groq_client.chat_json([
            {"role": "system", "content": "You art-direct memoir illustrations."},
            {"role": "user", "content": f"""Chapter "{chapter['title']}" ({chapter.get('era','')}) of the memoir
"{plan.get('title','A Life')}".

EXCERPT:
\"\"\"{text[:5000]}\"\"\"

Return STRICT JSON: {{"images": [{{"prompt": "...", "caption": "..."}}]}}
Exactly {n} entries, each a distinct moment from THIS chapter, in narrative order.
- "prompt": 25-40 words describing a photographic scene: subject, action, setting,
  era-accurate clothing and objects, time of day, mood. No names, no text in image.
- "caption": a short italic-style book caption (max 12 words)."""}],
            temperature=0.8, max_tokens=1600)
        items = data.get("images") or []
    except Exception:
        items = []

    if len(items) < n:
        for beat in (chapter.get("beats") or [])[: n - len(items)]:
            items.append({"prompt": f"{beat}, {chapter.get('era','')}", "caption": beat})
    while len(items) < n:
        items.append({"prompt": f"{chapter['title']}, {chapter.get('era','')}",
                      "caption": chapter["title"]})

    out = []
    for item in items[:n]:
        prompt = str(item.get("prompt") or chapter["title"])
        out.append({
            "prompt": prompt,
            "caption": str(item.get("caption") or "")[:120],
            "url": images.image_url(prompt),
        })
    return out


def _clean(text: str) -> str:
    text = re.sub(r"^\s*(here (is|'s)|certainly|sure[,!])[^\n]*\n+", "", text, flags=re.I)
    text = re.sub(r"^#{1,6}\s.*$", "", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def word_count(payload: dict) -> int:
    return sum(len((c.get("text") or "").split()) for c in payload.get("chapters", []))


# ------------------------------------------------------------------- demo mode
DEMO_TITLES = [
    ("The Long Way Home", "Beginnings"), ("Kitchen Table Gospels", "Family"),
    ("First Light", "School years"), ("Crossings", "Leaving home"),
    ("The Work of Hands", "Early career"), ("What We Carried", "Love"),
    ("Storm Season", "Hard years"), ("A Room of Our Own", "Building a life"),
    ("Small Mercies", "Friendship"), ("Turning", "Reinvention"),
    ("Harvest", "Later years"), ("Everything I Meant to Say", "Legacy"),
]


def demo_plan(transcript: str) -> dict:
    return {
        "title": "The Long Way Home",
        "subtitle": "A life told out loud (demo draft)",
        "narrator": "first",
        "voice_notes": "Plain-spoken, warm, wry.",
        "dedication": "For everyone who listened.",
        "demo": True,
        "chapters": [
            {"number": i + 1, "title": t, "era": era,
             "summary": f"A chapter shaped around what you told us about {era.lower()}.",
             "beats": ["an arrival", "a conflict", "a small kindness", "a decision"],
             "emotional_turn": "The narrator understands something they could not name before."}
            for i, (t, era) in enumerate(DEMO_TITLES[: config.TARGET_CHAPTERS])
        ],
    }


def demo_chapter(transcript: str, chapter: dict) -> str:
    seeds = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript) if len(s.strip()) > 20]
    seeds = seeds or ["I have been trying to tell this story for a long time."]
    paras = []
    for i in range(9):
        seed = seeds[(chapter["number"] * 3 + i) % len(seeds)]
        paras.append(textwrap.fill(
            f"{seed} That is how it began, at least the way I remember it now. "
            f"In {chapter.get('era','those years').lower()}, the days had a shape you could "
            "hold: the same light through the same window, the same voices carrying up "
            "from the street. I did not know yet which parts I would keep. "
            "Looking back, the small things are the ones that stayed — a door left open, "
            "a name called across a room, the particular silence after. "
            "This is a demonstration draft: add your GROQ_API_KEY and Lifescroll will "
            "rewrite this chapter with Llama 3.3 70B in seconds.", 100000))
    return "\n\n".join(paras)


# ---------------------------------------------------------------------- runner
_jobs_lock = threading.Lock()


def generate(bio_id: str, transcript: str, subject_hint: str = "") -> None:
    """Runs in a background thread; writes progress into the database."""
    def step(progress: float, stage: str, **extra):
        db.update_biography(bio_id, progress=round(progress, 3), stage=stage, **extra)

    try:
        live = groq_client.available()
        step(0.04, "Reading your interview…", status="running")

        plan = build_plan(transcript, subject_hint) if live else demo_plan(transcript)
        payload = {
            "title": plan.get("title", "A Life"),
            "subtitle": plan.get("subtitle", ""),
            "dedication": plan.get("dedication", ""),
            "demo": not live,
            "model": config.GROQ_MODEL if live else "demo-writer",
            "chapters": [{"number": c["number"], "title": c["title"], "era": c.get("era", ""),
                          "summary": c.get("summary", ""), "text": "", "images": [],
                          "status": "pending"}
                         for c in plan["chapters"]],
        }
        db.update_biography(bio_id, title=payload["title"], subtitle=payload["subtitle"],
                            payload=payload, progress=0.10,
                            stage=f"Outlined {len(payload['chapters'])} chapters")

        total = len(plan["chapters"])
        done = {"n": 0}

        def work(index: int, planned: dict) -> tuple:
            text = write_chapter(transcript, plan, planned) if live \
                else demo_chapter(transcript, planned)
            imgs = chapter_images(plan, planned, text) if live else [
                {"prompt": f"{planned['title']}, {planned.get('era','')}",
                 "caption": planned["title"],
                 "url": images.image_url(f"{planned['title']}, {planned.get('era','')}")}
                for _ in range(config.IMAGES_PER_CHAPTER)]
            return index, text, imgs

        with futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(work, i, c) for i, c in enumerate(plan["chapters"])]
            for fut in futures.as_completed(jobs):
                try:
                    index, text, imgs = fut.result()
                except Exception as exc:  # one chapter failing must not kill the book
                    traceback.print_exc()
                    index, text, imgs = -1, "", []
                    print(f"[lifescroll] chapter failed: {exc}")
                with _jobs_lock:
                    current = db.get_biography(bio_id)
                    data = current["payload"] if current else payload
                    if index >= 0:
                        data["chapters"][index]["text"] = text
                        data["chapters"][index]["images"] = imgs
                        data["chapters"][index]["status"] = "done"
                        data["chapters"][index]["words"] = len(text.split())
                    done["n"] += 1
                    pct = 0.10 + 0.85 * (done["n"] / max(1, total))
                    db.update_biography(
                        bio_id, payload=data, progress=round(pct, 3),
                        stage=f"Wrote {done['n']} of {total} chapters")

        final = db.get_biography(bio_id)
        data = final["payload"]
        data["word_count"] = word_count(data)
        data["estimated_pages"] = max(1, round(data["word_count"] / 450) +
                                      len(data["chapters"]) + 3)
        db.update_biography(bio_id, payload=data, progress=1.0, status="complete",
                            stage="Your biography is ready")
    except Exception as exc:
        traceback.print_exc()
        db.update_biography(bio_id, status="failed", stage="Generation failed",
                            error=str(exc)[:500])


def start(bio_id: str, transcript: str, subject_hint: str = "") -> None:
    threading.Thread(target=generate, args=(bio_id, transcript, subject_hint),
                     daemon=True).start()
