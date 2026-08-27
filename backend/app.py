"""Lifescroll API + static host."""
import io
import os
import re

from flask import (Flask, Response, g, jsonify, request, send_file,
                   send_from_directory)
from flask_cors import CORS

from . import auth, biographer, config, db, groq_client, images, interview, pdf_export

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "frontend")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
CORS(app, resources={r"/api/*": {"origins": "*"}})
db.init()


# ---------------------------------------------------------------------- static
@app.get("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


@app.get("/<path:path>")
def static_files(path):
    full = os.path.join(FRONTEND, path)
    if os.path.isfile(full):
        return send_from_directory(FRONTEND, path)
    return send_from_directory(FRONTEND, "index.html")


# ------------------------------------------------------------------------ meta
@app.get("/api/config")
def api_config():
    return jsonify(config.public_config())


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "groq": groq_client.available(),
                    "supabase": config.USE_SUPABASE})


# ------------------------------------------------------------------------ auth
@app.post("/api/auth/signup")
def api_signup():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(auth.signup(body.get("email", ""), body.get("password", ""),
                                   body.get("name", "")))
    except auth.AuthError as exc:
        return jsonify({"error": exc.message}), exc.status


@app.post("/api/auth/login")
def api_login():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(auth.login(body.get("email", ""), body.get("password", "")))
    except auth.AuthError as exc:
        return jsonify({"error": exc.message}), exc.status


@app.get("/api/auth/me")
@auth.require_auth
def api_me():
    return jsonify({"user": g.user})


# ------------------------------------------------------------------- interview
@app.get("/api/interview/spine")
def api_spine():
    return jsonify({"questions": interview.spine(),
                    "total_minutes": sum(s["minutes"] for s in interview.SPINE)})


@app.post("/api/interview/followup")
@auth.require_auth
def api_followup():
    body = request.get_json(silent=True) or {}
    return jsonify(interview.follow_up(body.get("question", ""), body.get("answer", ""),
                                       body.get("asked", []) or []))


# ----------------------------------------------------------------- biographies
@app.post("/api/biographies")
@auth.require_auth
def api_create_biography():
    body = request.get_json(silent=True) or {}
    answers = body.get("answers") or []
    transcript = (body.get("transcript") or "").strip() \
        or interview.transcript_from(answers)
    if len(transcript.split()) < 40:
        return jsonify({"error": "Tell us a bit more first — we need at least a few "
                                 "minutes of story to write a book."}), 400
    bio = db.create_biography(g.user["id"], transcript,
                              title=body.get("title") or "Untitled Life")
    biographer.start(bio["id"], transcript, body.get("subject_hint", ""))
    return jsonify({"id": bio["id"], "status": "queued"}), 202


@app.get("/api/biographies")
@auth.require_auth
def api_list_biographies():
    return jsonify({"biographies": db.list_biographies(g.user["id"])})


@app.get("/api/biographies/<bio_id>")
@auth.require_auth
def api_get_biography(bio_id):
    bio = db.get_biography(bio_id)
    if not bio or bio["user_id"] != g.user["id"]:
        return jsonify({"error": "Not found"}), 404
    include_text = request.args.get("full", "1") == "1"
    payload = bio["payload"]
    if not include_text:
        payload = {**payload, "chapters": [{k: v for k, v in c.items() if k != "text"}
                                           for c in payload.get("chapters", [])]}
    return jsonify({
        "id": bio["id"], "status": bio["status"], "progress": bio["progress"],
        "stage": bio["stage"], "error": bio["error"], "title": bio["title"],
        "subtitle": bio["subtitle"], "created_at": bio["created_at"],
        "book": payload,
    })


@app.delete("/api/biographies/<bio_id>")
@auth.require_auth
def api_delete_biography(bio_id):
    return jsonify({"deleted": db.delete_biography(bio_id, g.user["id"])})


@app.get("/api/biographies/<bio_id>/pdf")
def api_pdf(bio_id):
    # Token may arrive as a query param because <a download> can't set headers.
    token = auth.bearer_token() or request.args.get("token", "")
    try:
        user = auth.user_from_token(token)
    except auth.AuthError as exc:
        return jsonify({"error": exc.message}), exc.status

    bio = db.get_biography(bio_id)
    if not bio or bio["user_id"] != user["id"]:
        return jsonify({"error": "Not found"}), 404
    if bio["status"] != "complete":
        return jsonify({"error": "Biography is still being written."}), 409

    pdf = pdf_export.build_pdf(bio, user.get("email", ""))
    slug = re.sub(r"[^a-z0-9]+", "-", (bio["title"] or "biography").lower()).strip("-")
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{slug or 'lifescroll'}.pdf")


# ---------------------------------------------------------------------- images
@app.get("/api/image")
def api_image():
    """Server-side proxy used only when IMAGE_PROVIDER=openai (DALL-E)."""
    prompt = request.args.get("prompt", "")
    url = images.resolve_openai(prompt)
    data = images.fetch_bytes(url) if url else None
    if not data:
        return jsonify({"error": "image unavailable"}), 502
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(FRONTEND, "index.html")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
