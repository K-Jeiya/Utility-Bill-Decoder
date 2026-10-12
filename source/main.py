"""Utility Bill Decoder - command line entry point.

Examples (run from the `source` folder, venv active):
  python main.py --check-model
  python main.py --mode train --demo-questions
  python main.py --mode test
  python main.py --mode test --validate-only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from bill_extractor import expected_provider, extract_bill
from cache import Cache, fingerprint
from config import GUIDE_SAMPLE_QUESTIONS, PROJECT_ROOT, PROMPT_VERSION, ConfigError, Settings, load_settings
from llm_client import GeminiClient, LLMError, LLMFatalError, load_image
from question_answerer import answer_questions
from validators import (LEVEL1_COLUMNS, LEVEL2_COLUMNS, Issue, build_report, fatal, read_csv_strict,
                        validate_level1_file, validate_level2_file, write_csv)

log = logging.getLogger("bill_decoder")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def setup_logging(logs_dir: Path) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_log = logs_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fh = logging.FileHandler(run_log, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    eh = logging.FileHandler(logs_dir / "errors.log", encoding="utf-8")
    eh.setLevel(logging.WARNING)
    eh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    root.handlers = [fh, eh, ch]
    for noisy in ("httpx", "httpcore", "google_genai", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return run_log


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Utility Bill Decoder (WTQ Build Track)")
    p.add_argument("--mode", choices=["train", "test"], default="test",
                   help="train: process data/train/bills (no templates). test: use official templates in data/test/csv.")
    p.add_argument("--bills-dir", type=Path)
    p.add_argument("--level1-template", type=Path)
    p.add_argument("--level2-template", type=Path)
    p.add_argument("--out-dir", type=Path)
    p.add_argument("--only", metavar="BILL_ID", help="process a single bill (writes to a separate *_partial folder)")
    p.add_argument("--demo-questions", action="store_true",
                   help="train mode only: also answer the 2 sample questions printed in the guide")
    p.add_argument("--no-cache", action="store_true", help="ignore cached model results")
    p.add_argument("--show", action="store_true", help="print Level 1 JSON and Level 2 answers in the terminal")
    p.add_argument("--check-model", action="store_true", help="verify API key + model ID, then exit")
    p.add_argument("--validate-only", action="store_true", help="only validate existing output files")
    return p.parse_args()


def find_images(folder: Path) -> dict[str, Path]:
    return {p.stem: p for p in sorted(folder.iterdir()) if p.suffix.lower() in IMAGE_SUFFIXES}


def load_templates(l1: Path, l2: Path) -> tuple[list[dict], list[dict]]:
    c1, r1 = read_csv_strict(l1)
    c2, r2 = read_csv_strict(l2)
    if c1 != LEVEL1_COLUMNS:
        raise ConfigError(f"{l1} columns are {c1}, expected {LEVEL1_COLUMNS}")
    if c2 != LEVEL2_COLUMNS:
        raise ConfigError(f"{l2} columns are {c2}, expected {LEVEL2_COLUMNS}")
    return r1, r2


def process_bill(client, settings: Settings, cache: Cache, bill_id: str, image_path: Path,
                 questions: list[tuple[str, str]]) -> tuple[dict | None, dict[str, str], list[Issue]]:
    image, mime = load_image(image_path)
    issues: list[Issue] = []
    base = fingerprint(image, settings.model_name, PROMPT_VERSION)

    cached = cache.get(f"{bill_id}.extract", base)
    if cached:
        log.info("  Level 1: using cached result")
        bill, facts = cached["bill"], cached["facts"]
        from validators import validate_bill
        issues += validate_bill(bill, bill_id, expected_provider(bill_id))
    else:
        log.info("  Level 1: extracting with %s ...", settings.model_name)
        res = extract_bill(client, bill_id, image, mime, settings.max_output_attempts)
        bill, facts, issues = res.bill, res.facts, issues + res.issues
        if bill is not None:
            cache.put(f"{bill_id}.extract", base, {"bill": bill, "facts": facts})

    answers: dict[str, str] = {}
    if questions:
        qkey = fingerprint(base, json.dumps(bill, sort_keys=True), json.dumps(facts, sort_keys=True),
                           json.dumps(questions))
        cached_qa = cache.get(f"{bill_id}.qa", qkey)
        if cached_qa:
            log.info("  Level 2: using cached answers")
            answers = cached_qa
        else:
            log.info("  Level 2: answering %d questions ...", len(questions))
            answers, qa_issues = answer_questions(client, bill_id, image, mime, bill, facts, questions,
                                                  settings.max_output_attempts)
            issues += qa_issues
            if len(answers) == len(questions):
                cache.put(f"{bill_id}.qa", qkey, answers)
    return bill, answers, issues


def main() -> int:
    args = parse_args()
    train = args.mode == "train"
    data = PROJECT_ROOT / "data" / args.mode
    bills_dir = args.bills_dir or data / "bills"
    l1_tpl = args.level1_template or data / "csv" / "level1.csv"
    l2_tpl = args.level2_template or data / "csv" / "level2.csv"
    out_dir = args.out_dir or PROJECT_ROOT / ("output_train" if train else "output")
    if args.only and not args.out_dir:
        out_dir = PROJECT_ROOT / f"{out_dir.name}_partial"

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2
    run_log = setup_logging(settings.logs_dir)
    log.info("Model: %s/%s | key: %s | log: %s", settings.provider, settings.model_name, settings.masked_key, run_log)

    if args.check_model:
        try:
            print("Model reply:", GeminiClient(settings).check_model())
            print("OK: the key works and the model ID is available.")
            return 0
        except LLMFatalError as exc:
            print(f"MODEL CHECK FAILED: {exc}")
            return 2

    # ---- inputs -------------------------------------------------------------
    if not bills_dir.is_dir():
        print(f"Bills folder not found: {bills_dir}\nDownload the data first (see README).")
        return 2
    images = find_images(bills_dir)
    if train:
        l1_rows = [{"bill_id": b, "json": ""} for b in images]
        l2_rows = ([{"bill_id": b, "question_id": q, "question": t, "answer": ""}
                    for b in images for q, t in GUIDE_SAMPLE_QUESTIONS] if args.demo_questions else [])
    else:
        for tpl in (l1_tpl, l2_tpl):
            if not tpl.is_file():
                print(f"Official template not found: {tpl}\nDownload the test data at 12:30 PM (see README).")
                return 2
        try:
            l1_rows, l2_rows = load_templates(l1_tpl, l2_tpl)
        except (ConfigError, UnicodeDecodeError, OSError) as exc:
            print(f"TEMPLATE ERROR: {exc}")
            return 2
    if args.only:
        l1_rows = [r for r in l1_rows if r["bill_id"] == args.only]
        l2_rows = [r for r in l2_rows if r["bill_id"] == args.only]
        if not l1_rows:
            print(f"--only {args.only}: not found in the bill list")
            return 2
    # ---- templates are never modified: work on copies --------------------------
    l1_out = [dict(r) for r in l1_rows]
    l2_out = [dict(r) for r in l2_rows]
    full_test_run = (not train) and not args.only
    out1, out2 = out_dir / "level1.csv", out_dir / "level2.csv"
    all_issues: list[Issue] = []

    if not args.validate_only:
        client = GeminiClient(settings)
        cache = Cache(settings.logs_dir / "cache", enabled=not args.no_cache)
        questions_by_bill: dict[str, list[tuple[str, str]]] = {}
        for r in l2_out:
            questions_by_bill.setdefault(r["bill_id"], []).append((r["question_id"], r["question"]))
        results: dict[str, tuple[dict | None, dict[str, str]]] = {}

        for n, row in enumerate(l1_out, start=1):
            bid = row["bill_id"]
            log.info("[%d/%d] %s", n, len(l1_out), bid)
            if bid not in images:
                all_issues.append(fatal(bid, "image_missing", f"no image named {bid}.png/.jpg in {bills_dir}"))
                continue
            try:
                bill, answers, issues = process_bill(client, settings, cache, bid, images[bid],
                                                     questions_by_bill.get(bid, []))
            except LLMFatalError as exc:
                print(f"\nSTOPPING: unrecoverable API problem: {exc}")
                all_issues.append(fatal(bid, "api_fatal", str(exc)))
                break
            except (LLMError, OSError, ValueError) as exc:
                log.error("%s failed: %s", bid, exc)
                all_issues.append(fatal(bid, "bill_failed", str(exc)))
                continue
            all_issues += issues
            results[bid] = (bill, answers)
            if bill is not None:
                row["json"] = json.dumps(bill, ensure_ascii=False, separators=(",", ":"))
            for r in l2_out:
                if r["bill_id"] == bid:
                    r["answer"] = answers.get(r["question_id"], "")
            if args.show:
                print(f"\n--- {bid} Level 1 ---\n{json.dumps(bill, indent=2, ensure_ascii=False)}")
                for r in l2_out:
                    if r["bill_id"] == bid and r["answer"]:
                        print(f"\n{r['question_id']}: {r['question']}\n  -> {r['answer']}")

        write_csv(out1, LEVEL1_COLUMNS, l1_out)
        write_csv(out2, LEVEL2_COLUMNS, l2_out)
        log.info("Wrote %s and %s (%d API calls)", out1, out2, client.calls)

    # ---- validation of the files that are actually on disk ----------------------
    if not out1.is_file() or not out2.is_file():
        print("Output files not found; run without --validate-only first.")
        return 2
    exp1 = 10 if full_test_run else None
    exp2 = 120 if full_test_run else None
    file_issues = validate_level1_file(out1, l1_rows, exp1)
    file_issues += validate_level2_file(out2, l2_rows, exp2, expected_per_bill=12 if full_test_run else None) \
        if l2_rows else []
    # The same warning can appear in extraction and file validation: de-duplicate.
    seen: set[tuple] = set()
    merged = []
    for i in all_issues + file_issues:
        key = (i.severity, i.bill_id, i.code, i.message)
        if key not in seen:
            seen.add(key)
            merged.append(i)

    report_path = PROJECT_ROOT / "reports" / f"validation_report_{args.mode}{'_partial' if args.only else ''}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {"mode": args.mode, "model": f"{settings.provider}/{settings.model_name}",
               "level1 rows": len(l1_rows), "level2 rows": len(l2_rows),
               "level1 file": str(out1), "level2 file": str(out2)}
    report_path.write_text(build_report("Validation report", merged, summary), encoding="utf-8")
    n_fatal = sum(i.severity == "fatal" for i in merged)
    n_warn = len(merged) - n_fatal
    print(f"\nValidation: {n_fatal} fatal, {n_warn} warnings. Report: {report_path}")
    for i in merged:
        if i.severity == "fatal":
            print("  ", i)
    if n_fatal:
        print("Do NOT submit yet: fix the fatal items (re-running reuses cached successes).")
    return 1 if n_fatal else 0


if __name__ == "__main__":
    sys.exit(main())
