"""Vercel Python entrypoint: exposes the Flask WSGI app."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app  # noqa: E402

# Vercel's Python runtime looks for a WSGI callable named `app`.
application = app
