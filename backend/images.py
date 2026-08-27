"""Chapter illustrations.

Default provider is Pollinations (free, no API key). Set IMAGE_PROVIDER=openai
with OPENAI_API_KEY to use DALL-E 3 instead.
"""
import hashlib
import urllib.parse
from typing import Optional

import requests

from . import config

STYLE = ("cinematic editorial illustration, warm nostalgic film grain, soft golden "
         "light, painterly detail, memoir book plate, no text, no watermark")


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) % 1_000_000


def image_url(prompt: str, width: int = 1024, height: int = 576) -> str:
    """A stable, cacheable URL the browser can render directly."""
    full = f"{prompt.strip()}, {STYLE}"
    if config.IMAGE_PROVIDER == "openai" and config.OPENAI_API_KEY:
        # Resolved lazily server-side (DALL-E URLs expire), see resolve_openai().
        return "/api/image?" + urllib.parse.urlencode({"prompt": full})
    encoded = urllib.parse.quote(full, safe="")
    params = urllib.parse.urlencode({
        "width": width, "height": height, "seed": _seed(full),
        "nologo": "true", "model": "flux",
    })
    return f"https://image.pollinations.ai/prompt/{encoded}?{params}"


def resolve_openai(prompt: str) -> Optional[str]:
    if not config.OPENAI_API_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            json={"model": "dall-e-3", "prompt": prompt[:3900], "n": 1,
                  "size": "1792x1024"},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["url"]
    except Exception:
        return None


def fetch_bytes(url: str, timeout: int = 90) -> Optional[bytes]:
    """Download an illustration (used when embedding images into the PDF)."""
    try:
        if url.startswith("/api/image?"):
            prompt = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(
                "prompt", [""])[0]
            resolved = resolve_openai(prompt)
            if not resolved:
                return None
            url = resolved
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        return None
    return None
