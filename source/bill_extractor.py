"""Level 1: read one bill image with the vision model and return a validated JSON object."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from llm_client import LLMError, LLMFatalError
from prompts import build_extraction_prompt
from validators import (CONSISTENCY_CODES, Issue, JSONParseError, fatal, normalize_bill,
                        normalize_date, normalize_month, parse_json_loose, to_number, validate_bill)

log = logging.getLogger("bill_decoder.extract")

EXPECTED_PROVIDER_BY_PREFIX = {"KESC": "KE", "KE": "KE", "LESCO": "LESCO", "IESCO": "IESCO"}


def expected_provider(bill_id: str) -> str | None:
    return EXPECTED_PROVIDER_BY_PREFIX.get(bill_id.split("_")[0].upper())


@dataclass
class ExtractionResult:
    bill: dict | None
    facts: dict
    issues: list[Issue] = field(default_factory=list)
    attempts: int = 0


def clean_facts(raw: Any) -> dict:
    """Keep only well-formed extra facts (numbers coerced, bad rows dropped)."""
    if not isinstance(raw, dict):
        return {}
    facts: dict[str, Any] = {}

    def num(v):
        try:
            return to_number(v)[0]
        except ValueError:
            return None

    hist = []
    for h in raw.get("usage_history") or []:
        if isinstance(h, dict) and num(h.get("units")) is not None:
            month = normalize_month(h.get("month"))[0]
            hist.append({"month": month if isinstance(month, str) else None, "units": num(h["units"])})
    facts["usage_history"] = hist

    bh = []
    for h in raw.get("billing_history") or []:
        if isinstance(h, dict):
            pd = normalize_date(h.get("payment_date"))[0]
            bh.append({"month": normalize_month(h.get("month"))[0] if isinstance(h.get("month"), str) else None,
                       "billed_amount": num(h.get("billed_amount")),
                       "payment_date": pd if isinstance(pd, str) else None,
                       "paid_amount": num(h.get("paid_amount"))})
    facts["billing_history"] = bh

    facts["late_payment_amounts"] = [
        {"description": str(x.get("description", "")), "amount": num(x.get("amount"))}
        for x in raw.get("late_payment_amounts") or [] if isinstance(x, dict) and num(x.get("amount")) is not None]
    facts["printed_percent_split"] = [
        {"label": str(x.get("label", "")), "percent": num(x.get("percent"))}
        for x in raw.get("printed_percent_split") or [] if isinstance(x, dict) and num(x.get("percent")) is not None]
    for key in ("message_board_text", "notes"):
        v = raw.get(key)
        facts[key] = v.strip() if isinstance(v, str) and v.strip() else None
    return facts


def _split_response(parsed: Any) -> tuple[dict, dict]:
    """Accept {"bill":..., "facts":...}; tolerate a bare bill object."""
    if not isinstance(parsed, dict):
        raise JSONParseError("top-level JSON is not an object")
    if isinstance(parsed.get("bill"), dict):
        return parsed["bill"], parsed.get("facts") or {}
    if "provider" in parsed and "current_bill" in parsed:
        return parsed, {}
    raise JSONParseError("response has no 'bill' object")


def extract_bill(client, bill_id: str, image: bytes, mime: str, max_attempts: int) -> ExtractionResult:
    """Call the model, validate in Python, retry (limited) on bad or inconsistent output."""
    exp = expected_provider(bill_id)
    feedback: str | None = None
    best: ExtractionResult | None = None
    consistency_retry_used = False
    last_problem = "no attempt made"

    for attempt in range(1, max_attempts + 1):
        try:
            raw_text = client.generate_json(build_extraction_prompt(feedback), image, mime,
                                            label=f"{bill_id}:extract#{attempt}")
        except LLMFatalError:
            raise
        except LLMError as exc:
            last_problem = str(exc)
            log.error("%s: %s", bill_id, exc)
            continue
        try:
            raw_bill, raw_facts = _split_response(parse_json_loose(raw_text))
        except JSONParseError as exc:
            last_problem = f"unparseable response: {exc}"
            feedback = f"Your response was not usable JSON ({exc}). Return only the JSON object described."
            log.warning("%s attempt %d: %s", bill_id, attempt, last_problem)
            continue

        bill, notes = normalize_bill(raw_bill)
        for n in notes:
            log.debug("%s normalisation: %s", bill_id, n)
        issues = validate_bill(bill, bill_id, exp)
        fatals = [i for i in issues if i.severity == "fatal"]
        if fatals:
            last_problem = "; ".join(i.message for i in fatals)
            feedback = "\n".join(f"- {i.code}: {i.message}" for i in fatals)
            log.warning("%s attempt %d fatal issues: %s", bill_id, attempt, last_problem)
            continue

        candidate = ExtractionResult(bill, clean_facts(raw_facts), issues, attempt)
        if best is None or len(issues) < len(best.issues):
            best = candidate
        suspicious = [i for i in issues if i.code in CONSISTENCY_CODES]
        if not suspicious or consistency_retry_used or attempt == max_attempts:
            break
        consistency_retry_used = True  # exactly one extra look at suspicious totals
        feedback = ("The printed amounts did not add up in your last answer:\n"
                    + "\n".join(f"- {i.message}" for i in suspicious)
                    + "\nRe-read those lines on the image for misread digits or missed/extra lines.")
        log.info("%s: re-reading once because of %s", bill_id, [i.code for i in suspicious])

    if best is None:
        return ExtractionResult(None, {}, [fatal(bill_id, "extraction_failed", last_problem)], max_attempts)
    return best
