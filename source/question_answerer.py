"""Level 2: answer the official questions for one bill (all 12 in one request, validated per id)."""
from __future__ import annotations

import logging
import re

from calculations import compute_all
from llm_client import LLMError, LLMFatalError
from prompts import build_qa_prompt
from validators import Issue, JSONParseError, check_answer_text, fatal, parse_json_loose, warn

log = logging.getLogger("bill_decoder.qa")


def _lookup(answers: dict, qid: str):
    if qid in answers:
        return answers[qid]
    lowered = {str(k).strip().lower(): v for k, v in answers.items()}
    return lowered.get(qid.strip().lower())


def answer_questions(client, bill_id: str, image: bytes, mime: str, bill: dict | None, facts: dict,
                     questions: list[tuple[str, str]], max_attempts: int) -> tuple[dict[str, str], list[Issue]]:
    """Return ({question_id: answer}, issues). Failed questions are simply absent - never invented."""
    computed = compute_all(bill, facts)
    answers: dict[str, str] = {}
    issues: list[Issue] = []
    pending = list(questions)
    feedback: str | None = None

    for attempt in range(1, max_attempts + 1):
        if not pending:
            break
        try:
            raw = client.generate_json(build_qa_prompt(bill, facts, computed, pending, feedback), image, mime,
                                       label=f"{bill_id}:qa#{attempt}")
            parsed = parse_json_loose(raw)
            got = parsed.get("answers", parsed) if isinstance(parsed, dict) else None
            if not isinstance(got, dict):
                raise JSONParseError("no 'answers' object")
        except LLMFatalError:
            raise
        except (LLMError, JSONParseError) as exc:
            feedback = f"Previous response unusable: {exc}. Return the JSON object with all question ids."
            log.warning("%s qa attempt %d: %s", bill_id, attempt, exc)
            continue

        problems: list[str] = []
        for qid, _ in pending:
            text = _lookup(got, qid)
            text = re.sub(r"\s+", " ", text).strip() if isinstance(text, str) else text
            bad = [p for p in check_answer_text(text) if p[0] == "fatal"]
            if bad:
                problems.append(f"{qid}: {bad[0][2]}")
                continue
            for sev, code, msg in check_answer_text(text):
                if sev == "warning":
                    issues.append(warn(f"{bill_id}/{qid}", code, msg))
            answers[qid] = text
        pending = [(q, t) for q, t in pending if q not in answers]
        feedback = ("Fix these answers (keep all others unchanged and answer only these ids):\n" + "\n".join(problems)
                    if problems else None)

    for qid, _ in pending:
        issues.append(fatal(f"{bill_id}/{qid}", "no_answer", "no valid answer after all attempts"))
    return answers, issues
