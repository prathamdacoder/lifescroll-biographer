# 📜 Lifescroll

**Talk for fifteen minutes. Get a 50-page illustrated biography.**

Lifescroll interviews you out loud in the browser, transcribes you with the Web Speech
API, and uses **Groq (Llama 3.3 70B)** to ghostwrite a twelve-chapter memoir in your own
voice — then illustrates every chapter and typesets the whole thing as a printable PDF.

---

## What's in the box

| Feature | How it works |
|---|---|
| **Sign in** | Supabase Auth (email/password **+ Google OAuth**) when configured; a local JWT + SQLite fallback so it runs with zero setup |
| **15-minute interview** | 12-question spine with a live timer, plus **AI follow-up questions** generated from what you actually said |
| **Voice input** | Web Speech API dictation (continuous, interim results) with typing as a fallback |
| **Biography** | 12 chapters × ~2,100 words ≈ **50 printed pages**, drafted 3-at-a-time in parallel on Groq |
| **Illustrations** | 6 (configurable 5–10) art-directed images per chapter — **72 total** — via Pollinations (free, keyless) or DALL·E 3 |
| **PDF export** | A5 book typeset with ReportLab: title page, dedication, contents, drop caps, plates + captions, page numbers |
| **Library** | Every book saved per user, resumable progress, delete |

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your GROQ_API_KEY
python -m backend.app         # http://localhost:5000
```

Without a `GROQ_API_KEY` the app still runs end-to-end in **demo mode** (placeholder prose,
real images, real PDF) so you can click through everything.

```bash
python -m tests.smoke         # 7 smoke tests: auth, interview, book, PDF, secret-scan
```

## Environment variables

All secrets come from the environment — **nothing is hardcoded** (there's a test that
enforces it).

| Variable | Required | Notes |
|---|---|---|
| `GROQ_API_KEY` | yes (for real books) | from console.groq.com |
| `GROQ_MODEL` | no | default `llama-3.3-70b-versatile` |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | no | enables Supabase Auth + Google OAuth |
| `SUPABASE_SERVICE_ROLE_KEY` | no | mirrors biographies into Postgres |
| `IMAGE_PROVIDER` | no | `pollinations` (default, keyless) or `openai` |
| `OPENAI_API_KEY` | only for DALL·E | |
| `SECRET_KEY` | prod | signs local JWTs |
| `TARGET_CHAPTERS` / `WORDS_PER_CHAPTER` / `IMAGES_PER_CHAPTER` | no | `12` / `2100` / `6` — book length dials |

## Supabase setup (optional but recommended)

1. Create a project → **SQL Editor** → run [`supabase/schema.sql`](supabase/schema.sql).
2. **Authentication → Providers → Google**: enable it and add your OAuth client.
3. **Authentication → URL Configuration**: add your deployed origin as a redirect URL.
4. Set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`.

The frontend flips to Supabase automatically — the "Continue with Google" button appears
only when Supabase is configured (`GET /api/config` tells the client which mode it's in).

## Deploy

**Vercel** (`vercel.json` included — Flask runs as a Python function, frontend as static):

```bash
vercel --prod
vercel env add GROQ_API_KEY        # + SUPABASE_* and SECRET_KEY
```

**Render / Fly / any Docker host** (`Dockerfile` + `render.yaml` included) — recommended if
you want long-running generation without serverless time limits:

```bash
docker build -t lifescroll . && docker run -p 8080:8080 -e GROQ_API_KEY=... lifescroll
```

**Netlify** hosts the SPA (`netlify.toml`); point its `/api/*` redirect at your API host.

> On serverless, set `SUPABASE_*` — the SQLite fallback lives on ephemeral disk and won't
> survive between invocations.

## API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/config` | non-secret feature flags |
| `POST` | `/api/auth/signup` · `/api/auth/login` | returns `{token, user}` |
| `GET` | `/api/auth/me` | verify session |
| `GET` | `/api/interview/spine` | the 12 questions |
| `POST` | `/api/interview/followup` | AI follow-up for one answer |
| `POST` | `/api/biographies` | start generation → `202 {id}` |
| `GET` | `/api/biographies/:id` | book + `progress` / `stage` (poll this) |
| `GET` | `/api/biographies/:id/pdf` | download the typeset book |
| `DELETE` | `/api/biographies/:id` | remove a book |

## Layout

```
backend/     app.py · auth.py · db.py · biographer.py · groq_client.py
             images.py · interview.py · pdf_export.py · config.py
frontend/    index.html · styles.css · app.js      (no build step, no framework)
supabase/    schema.sql
tests/       smoke.py
api/         index.py            (Vercel entrypoint)
```

Generation runs in a background thread and streams progress into the database, so the
browser just polls `GET /api/biographies/:id` — close the tab and come back to **My books**.
