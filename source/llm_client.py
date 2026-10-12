"""Thin wrapper around the Google Gen AI SDK: image input, throttling, retries, key masking."""
from __future__ import annotations

import io
import logging
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import errors, types
from PIL import Image

from config import Settings

MAX_SIDE = 3000  # downscale only very large images to keep requests small
MIME_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
log = logging.getLogger("bill_decoder.llm")


class LLMError(Exception):
    """Transient failure that persisted after all retries."""


class LLMFatalError(LLMError):
    """Non-retryable failure (bad key, unknown model, blocked request ...)."""


def load_image(path: Path) -> tuple[bytes, str]:
    """Return (bytes, mime). The original file is sent unchanged unless it is very large
    or carries an EXIF rotation flag (which the model would not see)."""
    mime = MIME_BY_SUFFIX.get(path.suffix.lower())
    if mime is None:
        raise ValueError(f"unsupported image type: {path.name}")
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as img:
        needs_rotation = img.getexif().get(274, 1) not in (1, None)
        too_big = max(img.size) > MAX_SIDE
        if not needs_rotation and not too_big:
            return raw, mime
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
        if too_big:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        if mime == "image/png":
            img.save(buf, format="PNG", optimize=True)
        else:
            img.convert("RGB").save(buf, format="JPEG", quality=92)
        return buf.getvalue(), mime


class GeminiClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.client = genai.Client(
            api_key=settings.api_key,
            http_options=types.HttpOptions(timeout=settings.request_timeout_s * 1000),
        )
        self._last_call = 0.0
        self.calls = 0

    def _mask(self, text: str) -> str:
        return text.replace(self.s.api_key, self.s.masked_key)

    def _throttle(self) -> None:
        wait = self.s.min_request_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def check_model(self) -> str:
        """Confirm the configured model ID exists for this key and answers a trivial request."""
        try:
            self.client.models.get(model=self.s.model_name)
            resp = self.client.models.generate_content(model=self.s.model_name, contents="Reply with the single word: ok")
            return (resp.text or "").strip()
        except errors.APIError as exc:
            raise LLMFatalError(self._mask(f"API error {exc.code}: {exc.message}")) from exc

    def generate_json(self, prompt: str, image: bytes | None = None, mime: str | None = None,
                      label: str = "") -> str:
        contents: list = []
        if image is not None:
            contents.append(types.Part.from_bytes(data=image, mime_type=mime or "image/png"))
        contents.append(prompt)
        cfg = types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=16384)
        if self.s.temperature is not None:
            cfg.temperature = self.s.temperature

        last_err = "unknown"
        for attempt in range(1, self.s.max_api_retries + 1):
            self._throttle()
            self.calls += 1
            try:
                resp = self.client.models.generate_content(model=self.s.model_name, contents=contents, config=cfg)
                text = resp.text
                if text and text.strip():
                    return text
                last_err = "empty response (possibly blocked or truncated)"
            except errors.APIError as exc:
                last_err = self._mask(f"API error {exc.code}: {exc.message}")
                if exc.code in (400, 401, 403, 404):
                    raise LLMFatalError(last_err) from exc
            except (httpx.HTTPError, TimeoutError, ConnectionError, ValueError) as exc:
                last_err = self._mask(f"{type(exc).__name__}: {exc}")
            delay = min(60, 5 * 2 ** (attempt - 1))
            log.warning("%s: attempt %d/%d failed (%s); retrying in %ds", label, attempt,
                        self.s.max_api_retries, last_err[:200], delay)
            time.sleep(delay)
        raise LLMError(f"{label}: gave up after {self.s.max_api_retries} attempts: {last_err[:300]}")
