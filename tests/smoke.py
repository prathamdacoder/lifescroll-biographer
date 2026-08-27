"""Smoke tests: run `python -m tests.smoke` with the server NOT required."""
import json
import os
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="lifescroll-test-"))
os.environ.setdefault("SECRET_KEY", "test-secret")

from unittest import mock  # noqa: E402

from backend import app as flask_app  # noqa: E402
from backend import biographer, config, groq_client, interview  # noqa: E402

EMAIL = "smoke@example.com"
PASSWORD = "supersecret123"

ANSWERS = [
    {"question": q, "answer": a} for q, a in [
        ("Where were you born?", "I was born in Cork in 1968 in a terraced house with my grandmother upstairs."),
        ("Childhood day?", "Coal smoke and toast in the mornings, then the dog along the quay before school."),
        ("Who shaped you?", "My grandmother Nell, who mended everything and taught me to read from newspapers."),
        ("First leap?", "At nineteen I took the ferry to Liverpool with forty pounds and a duffel bag."),
        ("Love?", "I met Marie at a dance hall in 1991; she asked me to dance because I was too shy."),
        ("Legacy?", "That I was there, that I tried, and the small kindnesses were the whole point."),
    ]
]


class Smoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = flask_app.app.test_client()

    def _token(self):
        res = self.client.post("/api/auth/signup", json={
            "email": EMAIL, "password": PASSWORD, "name": "Smoke"})
        if res.status_code == 409:
            res = self.client.post("/api/auth/login",
                                   json={"email": EMAIL, "password": PASSWORD})
        return res.get_json()["token"]

    def test_config(self):
        data = self.client.get("/api/config").get_json()
        self.assertIn("auth_provider", data)
        self.assertNotIn("groq_api_key", json.dumps(data).lower())

    def test_auth_required(self):
        self.assertEqual(self.client.get("/api/biographies").status_code, 401)

    def test_bad_password(self):
        self.client.post("/api/auth/signup", json={
            "email": EMAIL, "password": PASSWORD, "name": "Smoke"})
        res = self.client.post("/api/auth/login",
                               json={"email": EMAIL, "password": "wrong-password"})
        self.assertEqual(res.status_code, 401)

    def test_interview_spine(self):
        data = self.client.get("/api/interview/spine").get_json()
        self.assertEqual(len(data["questions"]), 12)
        self.assertGreaterEqual(data["total_minutes"], 15)

    def test_transcript_builder(self):
        text = interview.transcript_from(ANSWERS)
        self.assertIn("SUBJECT:", text)

    def test_end_to_end_book_and_pdf(self):
        token = self._token()
        auth = {"Authorization": f"Bearer {token}"}

        thin = self.client.post("/api/biographies", headers=auth,
                                json={"answers": ANSWERS[:1]})
        self.assertEqual(thin.status_code, 400)

        res = self.client.post("/api/biographies", headers=auth, json={"answers": ANSWERS})
        self.assertEqual(res.status_code, 202)
        bio_id = res.get_json()["id"]

        import time
        for _ in range(120):
            data = self.client.get(f"/api/biographies/{bio_id}?full=0", headers=auth).get_json()
            if data["status"] in ("complete", "failed"):
                break
            time.sleep(0.5)
        self.assertEqual(data["status"], "complete", data.get("error"))

        book = self.client.get(f"/api/biographies/{bio_id}", headers=auth).get_json()["book"]
        self.assertEqual(len(book["chapters"]), 12)
        self.assertTrue(all(c["text"] for c in book["chapters"]))
        self.assertTrue(all(len(c["images"]) >= 5 for c in book["chapters"]))
        self.assertGreater(book["word_count"], 5000)

        pdf = self.client.get(f"/api/biographies/{bio_id}/pdf?token={token}")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertGreater(len(pdf.data), 20000)

        self.assertTrue(self.client.delete(f"/api/biographies/{bio_id}",
                                           headers=auth).get_json()["deleted"])

    def test_default_model_is_qwen(self):
        self.assertEqual(config.GROQ_MODEL, "qwen/qwen3.6-27b")
        self.assertIn("qwen/qwen3.6-27b", config.GROQ_FALLBACK_MODELS)

    def test_model_fallback_and_reasoning_strip(self):
        """A decommissioned primary model must fall through to the next one."""
        calls = []

        class Resp:
            def __init__(self, status, payload=None, text=""):
                self.status_code, self._payload, self.text = status, payload, text

            def json(self):
                return self._payload

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append(json["model"])
            if json["model"] == "qwen/qwen3.6-27b":
                return Resp(404, text='{"error":{"code":"model_not_found",'
                                      '"message":"model has been decommissioned"}}')
            return Resp(200, {"choices": [{"message": {
                "content": "<think>plotting the chapter</think>The kettle went on at six."}}]})

        with mock.patch.object(groq_client.config, "GROQ_API_KEY", "gsk_test"), \
                mock.patch.object(groq_client.requests, "post", fake_post):
            groq_client._active = None
            groq_client._dead.clear()
            out = groq_client.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(out, "The kettle went on at six.")     # reasoning stripped
        self.assertEqual(calls[0], "qwen/qwen3.6-27b")          # tried the default first
        self.assertEqual(groq_client.active_model(), "openai/gpt-oss-120b")
        groq_client._active = None
        groq_client._dead.clear()

    def test_reasoning_params_sent_for_qwen(self):
        body = groq_client._payload("qwen/qwen3.6-27b", [], 0.7, 100, False)
        self.assertEqual(body["reasoning_effort"], "none")
        self.assertEqual(body["reasoning_format"], "hidden")
        self.assertNotIn("reasoning_effort",
                         groq_client._payload("llama-3.1-8b-instant", [], 0.7, 100, False))

    def test_no_hardcoded_secret(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        for path in list(root.glob("backend/*.py")) + list(root.glob("frontend/*.js")):
            text = path.read_text()
            self.assertNotRegex(text, r"gsk_[A-Za-z0-9]{20,}",
                                f"possible hardcoded Groq key in {path.name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
