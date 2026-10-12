"""Settings loaded from environment variables / the .env file.

Only the competition-approved model IDs are accepted. If MODEL_NAME is not on
the approved list we stop with an error instead of silently switching models.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SOURCE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SOURCE_DIR.parent

# Bump when prompts change so cached results from older prompts are not reused.
PROMPT_VERSION = "2026-10-10.1"

# Approved runtime models (competition guide, section 9.1).
ALLOWED_MODELS: dict[str, set[str]] = {
    "anthropic": {"claude-haiku-4-5"},
    "google": {"gemini-3.5-flash-lite", "gemini-3.1-flash-lite"},
    "openai": {"gpt-4.1-mini", "gpt-5-mini"},
}
# This project only implements the Google (Gemini) client.
IMPLEMENTED_PROVIDERS = {"google"}

# The two sample questions printed in the guide (section 6.2). Only used by the
# optional --demo-questions flag on training bills; never used for test CSVs.
GUIDE_SAMPLE_QUESTIONS = [
    ("Q1", "Which electricity provider issued this bill?"),
    ("Q2", "What is the bill month?"),
    ("Q3", "What is the bill issue date?"),
    ("Q4", "What is the payment due date?"),
    ("Q5", "How many electricity units were consumed?"),
    ("Q6", "What are the previous and current meter readings?"),
    ("Q7", "What is the total amount of charges before taxes?"),
    ("Q8", "What is the total amount of taxes?"),
    ("Q9", "What is the current bill amount?"),
    ("Q10", "How much are the outstanding arrears?"),
    ("Q11", "What is the payable amount before the due date?"),
    ("Q12", "What is the payable amount after the due date?"),
]


class ConfigError(Exception):
    """Raised when configuration is missing or not allowed."""


@dataclass(frozen=True)
class Settings:
    provider: str
    model_name: str
    api_key: str
    temperature: float | None
    max_output_attempts: int
    max_api_retries: int
    min_request_interval: float
    request_timeout_s: int
    logs_dir: Path

    @property
    def masked_key(self) -> str:
        """Never show more than the last 4 characters of the key."""
        return "****" + self.api_key[-4:] if len(self.api_key) > 8 else "****"


def _num(name: str, default: str, cast):
    raw = os.getenv(name, "").strip() or default
    try:
        return cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def load_settings() -> Settings:
    load_dotenv(SOURCE_DIR / ".env")
    load_dotenv()

    try:
        import streamlit as st
        secrets = st.secrets
        for name in (
            "MODEL_PROVIDER", "MODEL_NAME", "API_KEY", "TEMPERATURE",
            "MAX_OUTPUT_ATTEMPTS", "MAX_API_RETRIES",
            "MIN_REQUEST_INTERVAL_SECONDS", "REQUEST_TIMEOUT_SECONDS",
        ):
            if name in secrets:
                os.environ[name] = str(secrets[name])
    except Exception:
        pass

    provider = os.getenv("MODEL_PROVIDER", "google").strip().lower()
    model = os.getenv("MODEL_NAME", "").strip()
    key = os.getenv("API_KEY", "").strip()

    if provider not in ALLOWED_MODELS:
        raise ConfigError(f"MODEL_PROVIDER={provider!r} is not one of {sorted(ALLOWED_MODELS)}")
    if not model:
        raise ConfigError("MODEL_NAME is not set. Copy .env.example to .env (it contains the model ID).")
    if model not in ALLOWED_MODELS[provider]:
        raise ConfigError(
            f"MODEL_NAME={model!r} is not an approved {provider} model. "
            f"Approved: {sorted(ALLOWED_MODELS[provider])}"
        )
    if provider not in IMPLEMENTED_PROVIDERS:
        raise ConfigError(
            f"Provider {provider!r} is approved by the competition but not implemented here. "
            "Set MODEL_PROVIDER=google."
        )
    if not key or key == "your-api-key-here":
        raise ConfigError("API_KEY is missing. Copy .env.example to .env and add your own key.")

    temp_raw = os.getenv("TEMPERATURE", "").strip()
    temperature = float(temp_raw) if temp_raw else None

    return Settings(
        provider=provider,
        model_name=model,
        api_key=key,
        temperature=temperature,
        max_output_attempts=_num("MAX_OUTPUT_ATTEMPTS", "3", int),
        max_api_retries=_num("MAX_API_RETRIES", "5", int),
        min_request_interval=_num("MIN_REQUEST_INTERVAL_SECONDS", "4.5", float),
        request_timeout_s=_num("REQUEST_TIMEOUT_SECONDS", "180", int),
        logs_dir=PROJECT_ROOT / "logs",
    )
