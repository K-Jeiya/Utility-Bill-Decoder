"""Normalisation and validation for Level 1 JSON, Level 2 answers and the CSV files.

Two severities are used everywhere:
  * "fatal"   - the output is unusable/invalid and must be fixed before submitting.
  * "warning" - something looks suspicious (e.g. printed lines do not add up) but may be
                genuinely printed that way. Warnings never change any amount.
"""
from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCHEMA_KEYS = [
    "provider", "tariff", "sanctioned_load_kw", "bill_month", "reading_date", "issue_date",
    "due_date", "previous_reading", "current_reading", "units_consumed", "charges",
    "total_charges", "taxes", "total_taxes", "current_bill", "arrears",
    "payable_within_due_date", "payable_after_due_date",
]
PROVIDERS = {"KE", "LESCO", "IESCO"}
CHARGE_TYPES = {"energy", "fixed", "fpa", "quarterly_adjustment", "surcharge",
                "meter_rent", "subsidy", "other"}
TAX_TYPES = {"gst", "electricity_duty", "income_tax", "municipal_tax", "other_tax"}
NUMERIC_FIELDS = ["sanctioned_load_kw", "previous_reading", "current_reading", "units_consumed",
                  "total_charges", "total_taxes", "current_bill", "arrears",
                  "payable_within_due_date", "payable_after_due_date"]
DATE_FIELDS = ["reading_date", "issue_date", "due_date"]

# Charge/tax types the model sometimes invents -> the official category.
CHARGE_ALIASES = {"fca": "fpa", "fuel_price_adjustment": "fpa", "qta": "quarterly_adjustment",
                  "service_rent": "meter_rent", "energy_charge": "energy", "fixed_charge": "fixed"}
TAX_ALIASES = {"sales_tax": "gst", "ed": "electricity_duty", "duty": "electricity_duty",
               "muct": "municipal_tax", "kmc": "municipal_tax", "tv_fee": "other_tax", "other": "other_tax"}

LEVEL1_COLUMNS = ["bill_id", "json"]
LEVEL2_COLUMNS = ["bill_id", "question_id", "question", "answer"]

CNIC_RE = re.compile(r"\b\d{5}-?\d{7}-?\d\b")
LONG_DIGITS_RE = re.compile(r"\b\d{9,}\b")
URDU_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")


@dataclass
class Issue:
    severity: str  # "fatal" | "warning"
    bill_id: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.bill_id} {self.code}: {self.message}"


def fatal(bill_id: str, code: str, msg: str) -> Issue:
    return Issue("fatal", bill_id, code, msg)


def warn(bill_id: str, code: str, msg: str) -> Issue:
    return Issue("warning", bill_id, code, msg)


# ----------------------------------------------------------------- JSON parsing
class JSONParseError(ValueError):
    pass


def parse_json_loose(text: str) -> Any:
    """Parse model output as JSON, safely repairing the common cosmetic problems:
    Markdown fences, text around the object, and trailing commas. Nothing else is guessed."""
    if not isinstance(text, str) or not text.strip():
        raise JSONParseError("empty response")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise JSONParseError("no JSON object found")
    candidate = re.sub(r",\s*([}\]])", r"\1", cleaned[start:end + 1])
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise JSONParseError(f"invalid JSON: {exc}") from exc


# ----------------------------------------------------------------- value coercion
def to_number(value: Any) -> tuple[Any, bool]:
    """Return (number-or-None, was_coerced). Raises ValueError for unusable text."""
    if value is None:
        return None, False
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite number")
        return (int(value) if isinstance(value, float) and value.is_integer() else value), False
    if isinstance(value, str):
        s = value.strip()
        if s.lower() in {"", "null", "none", "n/a", "na", "-", "--"}:
            return None, True
        negative = False
        if re.search(r"\bCR\b|CR$", s, flags=re.I):
            negative = True
        if s.startswith("(") and s.endswith(")"):
            negative = True
        s = re.sub(r"(?i)\b(rs|pkr)\.?|cr\b|[(),\s]", "", s)
        if s.endswith("-") and s[:-1].replace(".", "", 1).isdigit():
            negative, s = True, s[:-1]
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            num = float(s)
            if negative and num > 0:
                num = -num
            return (int(num) if num.is_integer() else num), True
    raise ValueError(f"not numeric: {value!r}")


_DATE_FORMATS = ["%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d %b %y", "%d/%m/%Y", "%d-%m-%Y",
                 "%d %B %Y", "%d-%B-%Y", "%d/%m/%y", "%d.%m.%Y", "%b %d, %Y", "%B %d, %Y"]
_MONTH_FORMATS = ["%b %Y", "%B %Y", "%b-%y", "%b-%Y", "%B-%Y", "%b %y", "%m/%Y", "%m-%Y"]


def normalize_date(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, str):
        return value, False
    s = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s, False
    cleaned = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", s, flags=re.I).replace(",", ", ").replace("  ", " ").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned.title() if "%b" in fmt or "%B" in fmt else cleaned, fmt).strftime("%Y-%m-%d"), True
        except ValueError:
            continue
    return value, False


def normalize_month(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, str):
        return value, False
    s = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s, False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s[:7], True
    for fmt in _MONTH_FORMATS:
        try:
            return datetime.strptime(s.title(), fmt).strftime("%Y-%m"), True
        except ValueError:
            continue
    return value, False


def _is_real_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) is not None
    except ValueError:
        return False


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ----------------------------------------------------------------- Level 1 normalisation
def _normalize_items(items: Any, allowed: set[str], aliases: dict[str, str], fallback: str,
                     notes: list[str], label: str) -> Any:
    if items is None:
        return []
    if not isinstance(items, list):
        return items  # validate_bill reports it
    out = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            out.append(item)
            continue
        typ = str(item.get("type", "")).strip().lower().replace(" ", "_")
        if typ not in allowed:
            mapped = aliases.get(typ, fallback)
            notes.append(f"{label}[{idx}] type {typ!r} mapped to {mapped!r}")
            typ = mapped
        try:
            amount, coerced = to_number(item.get("amount"))
        except ValueError:
            out.append({"type": typ, "amount": item.get("amount")})  # flagged later
            continue
        if coerced:
            notes.append(f"{label}[{idx}] amount coerced to number")
        if amount is None or amount == 0:
            notes.append(f"{label}[{idx}] dropped (blank/zero amount)")
            continue
        out.append({"type": typ, "amount": amount})
    return out


def normalize_bill(raw: dict) -> tuple[dict, list[str]]:
    """Build a dict with exactly the schema keys, applying only safe, logged repairs."""
    notes: list[str] = []
    bill: dict[str, Any] = {}
    for key in SCHEMA_KEYS:
        bill[key] = raw.get(key) if isinstance(raw, dict) else None

    if isinstance(bill["provider"], str):
        p = bill["provider"].strip().upper()
        bill["provider"] = {"KESC": "KE", "K-ELECTRIC": "KE", "K ELECTRIC": "KE"}.get(p, p)
    if isinstance(bill["tariff"], str):
        bill["tariff"] = bill["tariff"].strip() or None
    for key in NUMERIC_FIELDS:
        try:
            bill[key], coerced = to_number(bill[key])
            if coerced:
                notes.append(f"{key} coerced to number")
        except ValueError:
            pass  # leave raw value so validation reports it
    for key in DATE_FIELDS:
        bill[key], coerced = normalize_date(bill[key])
        if coerced:
            notes.append(f"{key} reformatted")
    bill["bill_month"], coerced = normalize_month(bill["bill_month"])
    if coerced:
        notes.append("bill_month reformatted")
    bill["charges"] = _normalize_items(bill["charges"], CHARGE_TYPES, CHARGE_ALIASES, "other", notes, "charges")
    bill["taxes"] = _normalize_items(bill["taxes"], TAX_TYPES, TAX_ALIASES, "other_tax", notes, "taxes")
    return bill, notes


# ----------------------------------------------------------------- Level 1 validation
SUM_TOL = 1.0
CONSISTENCY_CODES = {"charges_sum_mismatch", "taxes_sum_mismatch", "bill_total_mismatch", "payable_mismatch"}


def validate_bill(bill: Any, bill_id: str, expected_provider: str | None = None) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(bill, dict):
        return [fatal(bill_id, "not_object", "Level 1 value is not a JSON object")]
    missing = [k for k in SCHEMA_KEYS if k not in bill]
    extra = [k for k in bill if k not in SCHEMA_KEYS]
    if missing:
        issues.append(fatal(bill_id, "missing_fields", f"missing: {missing}"))
    if extra:
        issues.append(fatal(bill_id, "extra_fields", f"unexpected: {extra}"))
    if missing:
        return issues

    if bill["provider"] not in PROVIDERS:
        issues.append(fatal(bill_id, "bad_provider", f"provider {bill['provider']!r} not in {sorted(PROVIDERS)}"))
    elif expected_provider and bill["provider"] != expected_provider:
        issues.append(warn(bill_id, "provider_vs_filename", f"provider {bill['provider']} but file name suggests {expected_provider}"))
    if bill["tariff"] is not None and not isinstance(bill["tariff"], str):
        issues.append(fatal(bill_id, "bad_tariff", "tariff must be a string or null"))
    for key in NUMERIC_FIELDS:
        if bill[key] is not None and not _is_number(bill[key]):
            issues.append(fatal(bill_id, "not_numeric", f"{key}={bill[key]!r} must be a number or null"))
    for key in DATE_FIELDS:
        v = bill[key]
        if v is not None and not (isinstance(v, str) and _is_real_date(v)):
            issues.append(fatal(bill_id, "bad_date", f"{key}={v!r} must be YYYY-MM-DD or null"))
    v = bill["bill_month"]
    if v is not None and not (isinstance(v, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v)):
        issues.append(fatal(bill_id, "bad_month", f"bill_month={v!r} must be YYYY-MM or null"))

    for field, allowed in (("charges", CHARGE_TYPES), ("taxes", TAX_TYPES)):
        items = bill[field]
        if not isinstance(items, list):
            issues.append(fatal(bill_id, f"bad_{field}", f"{field} must be a list"))
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict) or set(item) != {"type", "amount"}:
                issues.append(fatal(bill_id, f"bad_{field}_item", f"{field}[{i}] must be {{type, amount}}: {item!r}"))
                continue
            if item["type"] not in allowed:
                issues.append(fatal(bill_id, f"bad_{field}_type", f"{field}[{i}] type {item['type']!r} invalid"))
            if not _is_number(item["amount"]):
                issues.append(fatal(bill_id, f"bad_{field}_amount", f"{field}[{i}] amount {item['amount']!r} not numeric"))
            elif item["amount"] == 0:
                issues.append(warn(bill_id, "zero_line", f"{field}[{i}] has a zero amount (should be skipped)"))
            elif field == "charges" and item["type"] == "subsidy" and item["amount"] > 0:
                issues.append(warn(bill_id, "subsidy_positive", f"charges[{i}] subsidy is positive; subsidies must be negative"))
    if any(i.severity == "fatal" for i in issues):
        return issues
    return issues + _consistency_checks(bill, bill_id)


def _consistency_checks(b: dict, bid: str) -> list[Issue]:
    """Suspicion checks only. They never modify printed amounts."""
    out: list[Issue] = []
    num = _is_number

    if b["charges"] and num(b["total_charges"]):
        s = round(sum(c["amount"] for c in b["charges"]), 2)
        if abs(s - b["total_charges"]) > SUM_TOL:
            out.append(warn(bid, "charges_sum_mismatch", f"charge lines sum to {s} but total_charges is {b['total_charges']}"))
    if b["taxes"] and num(b["total_taxes"]):
        s = round(sum(t["amount"] for t in b["taxes"]), 2)
        if abs(s - b["total_taxes"]) > SUM_TOL:
            out.append(warn(bid, "taxes_sum_mismatch", f"tax lines sum to {s} but total_taxes is {b['total_taxes']}"))
    if all(num(b[k]) for k in ("total_charges", "total_taxes", "current_bill")):
        s = round(b["total_charges"] + b["total_taxes"], 2)
        if abs(s - b["current_bill"]) > SUM_TOL:
            out.append(warn(bid, "bill_total_mismatch", f"total_charges + total_taxes = {s} but current_bill is {b['current_bill']}"))
    if num(b["current_bill"]) and num(b["payable_within_due_date"]):
        arrears = b["arrears"] if num(b["arrears"]) else 0
        s = round(b["current_bill"] + arrears, 2)
        if abs(s - b["payable_within_due_date"]) > 1.5:
            out.append(warn(bid, "payable_mismatch", f"current_bill + arrears = {s} but payable_within_due_date is {b['payable_within_due_date']} (may be legitimate if other items are printed)"))
    if num(b["payable_within_due_date"]) and num(b["payable_after_due_date"]) \
            and b["payable_after_due_date"] < b["payable_within_due_date"]:
        out.append(warn(bid, "after_due_lower", "payable_after_due_date is lower than payable_within_due_date"))
    if all(num(b[k]) for k in ("previous_reading", "current_reading", "units_consumed")):
        diff = round(b["current_reading"] - b["previous_reading"], 2)
        if abs(diff - b["units_consumed"]) > 0.5:
            out.append(warn(bid, "units_vs_readings", f"current-previous = {diff} but units_consumed = {b['units_consumed']} (multiplier/adjusted units possible)"))
    dates = [b[k] for k in ("reading_date", "issue_date", "due_date")]
    if all(dates) and not (dates[0] <= dates[1] <= dates[2]):
        out.append(warn(bid, "date_order", f"expected reading <= issue <= due, got {dates}"))
    if b["bill_month"] and b["reading_date"]:
        y1, m1 = map(int, b["bill_month"].split("-"))
        y2, m2 = map(int, b["reading_date"][:7].split("-"))
        if abs((y1 * 12 + m1) - (y2 * 12 + m2)) > 1:
            out.append(warn(bid, "month_vs_reading", "bill_month differs from reading_date month by more than one month"))
    nulls = [k for k in SCHEMA_KEYS if b[k] is None]
    if len(nulls) >= 8:
        out.append(warn(bid, "many_nulls", f"{len(nulls)} fields are null: {nulls}"))
    return out


# ----------------------------------------------------------------- Level 2 answer checks
def find_pii(text: str) -> list[tuple[str, str]]:
    """Return [(severity, match)]. CNIC-like numbers are fatal, other long digit runs are warnings."""
    found = [("fatal", m.group(0)) for m in CNIC_RE.finditer(text)]
    plain = re.sub(r"(?<=\d),(?=\d{3})", "", text)  # 1,234,567 -> 1234567
    found += [("warning", m) for m in LONG_DIGITS_RE.findall(plain)]
    return found


def check_answer_text(answer: Any) -> list[tuple[str, str, str]]:
    """Return [(severity, code, message)] for one answer."""
    if not isinstance(answer, str) or not answer.strip():
        return [("fatal", "empty_answer", "answer is empty")]
    problems = []
    if len(answer.strip()) < 5:
        problems.append(("fatal", "too_short", "answer is too short"))
    if URDU_RE.search(answer):
        problems.append(("fatal", "not_english", "answer contains Urdu/Arabic script"))
    for sev, match in find_pii(answer):
        problems.append((sev, "possible_pii", f"possible personal identifier / long number: {match}"))
    return problems


# ----------------------------------------------------------------- CSV helpers + output validation
def read_csv_strict(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read UTF-8 CSV (BOM tolerated). Raises UnicodeDecodeError/csv.Error if invalid."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, strict=True)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)


def validate_level1_file(path: Path, template_rows: list[dict], expected_count: int | None) -> list[Issue]:
    issues: list[Issue] = []
    try:
        cols, rows = read_csv_strict(path)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return [fatal("level1.csv", "unreadable", f"{exc}")]
    if cols != LEVEL1_COLUMNS:
        issues.append(fatal("level1.csv", "columns", f"columns are {cols}, expected {LEVEL1_COLUMNS}"))
        return issues
    if expected_count is not None and len(rows) != expected_count:
        issues.append(fatal("level1.csv", "row_count", f"{len(rows)} rows, expected {expected_count}"))
    if [r["bill_id"] for r in rows] != [r["bill_id"] for r in template_rows]:
        issues.append(fatal("level1.csv", "row_order", "bill_id values/order differ from the template"))
    for row in rows:
        bid, cell = row["bill_id"], row["json"]
        if not cell.strip():
            issues.append(fatal(bid, "empty_json", "json cell is empty"))
            continue
        if "\n" in cell or "\r" in cell:
            issues.append(fatal(bid, "multiline_json", "JSON must be on one line"))
        try:
            obj = json.loads(cell)
        except json.JSONDecodeError as exc:
            issues.append(fatal(bid, "json_parse", str(exc)))
            continue
        prefix = bid.split("_")[0].upper()
        expected = {"KESC": "KE", "KE": "KE", "LESCO": "LESCO", "IESCO": "IESCO"}.get(prefix)
        issues.extend(validate_bill(obj, bid, expected))
    return issues


def validate_level2_file(path: Path, template_rows: list[dict], expected_count: int | None,
                         expected_per_bill: int | None = 12) -> list[Issue]:
    issues: list[Issue] = []
    try:
        cols, rows = read_csv_strict(path)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return [fatal("level2.csv", "unreadable", f"{exc}")]
    if cols != LEVEL2_COLUMNS:
        return [fatal("level2.csv", "columns", f"columns are {cols}, expected {LEVEL2_COLUMNS}")]
    if expected_count is not None and len(rows) != expected_count:
        issues.append(fatal("level2.csv", "row_count", f"{len(rows)} rows, expected {expected_count}"))
    if len(rows) != len(template_rows):
        issues.append(fatal("level2.csv", "row_count_vs_template", f"{len(rows)} rows but template has {len(template_rows)}"))
    for i, (row, tpl) in enumerate(zip(rows, template_rows), start=2):
        for col in ("bill_id", "question_id", "question"):
            if row[col] != tpl[col]:
                issues.append(fatal(f"{tpl['bill_id']}/{tpl['question_id']}", "template_changed", f"line {i}: column {col} differs from template"))
        for sev, code, msg in check_answer_text(row["answer"]):
            issues.append(Issue(sev, f"{row['bill_id']}/{row['question_id']}", code, msg))
    if expected_per_bill:
        counts: dict[str, int] = {}
        for r in rows:
            if r["answer"].strip():
                counts[r["bill_id"]] = counts.get(r["bill_id"], 0) + 1
        for bid in dict.fromkeys(r["bill_id"] for r in template_rows):
            if counts.get(bid, 0) != expected_per_bill:
                issues.append(fatal(bid, "answers_per_bill", f"{counts.get(bid, 0)} answered questions, expected {expected_per_bill}"))
    return issues


def build_report(title: str, issues: list[Issue], summary: dict[str, Any]) -> str:
    fatals = [i for i in issues if i.severity == "fatal"]
    warns = [i for i in issues if i.severity == "warning"]
    lines = [f"# {title}", "", f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}", ""]
    lines.append(f"**Result: {'FAILED - fix fatal errors before submitting' if fatals else 'no fatal errors'}** "
                 f"({len(fatals)} fatal, {len(warns)} warnings)")
    lines += ["", "## Summary", ""] + [f"- {k}: {v}" for k, v in summary.items()]
    lines += ["", "## Fatal errors", ""] + ([f"- {i.bill_id} `{i.code}`: {i.message}" for i in fatals] or ["- none"])
    lines += ["", "## Warnings (review manually against the bill images)", ""]
    lines += [f"- {i.bill_id} `{i.code}`: {i.message}" for i in warns] or ["- none"]
    lines += ["", "> Passing these checks only proves the files are well-formed and internally plausible. "
              "It does **not** prove the extracted values or answers are correct; compare a sample against the images."]
    return "\n".join(lines) + "\n"
