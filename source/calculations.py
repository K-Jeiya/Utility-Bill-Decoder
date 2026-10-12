"""Deterministic arithmetic done in Python, so the model never has to do maths.

The results are handed to the question-answering prompt as "computed facts".
All inputs are values printed on the bill; nothing here uses outside tariff data.
"""
from __future__ import annotations

import statistics
from typing import Any

THRESHOLDS = [50, 100, 150, 200, 250, 300, 400, 500, 600, 800, 1000]


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def split_history(history: list[dict], bill_month: str | None, units_consumed: Any) -> tuple[list[dict], dict | None]:
    """Separate the usage bars into previous months and the current month's bar.

    Bars are ordered oldest -> newest. The newest bar normally is the current month
    (the guide's KESC_0008 shows 13 bars: 12 previous + current)."""
    bars = [h for h in history if _num(h.get("units"))]
    if not bars:
        return [], None
    last = bars[-1]
    is_current = (bill_month and last.get("month") == bill_month) or \
                 (last.get("month") is None and _num(units_consumed) and last["units"] == units_consumed)
    if is_current:
        return bars[:-1], last
    return bars, None


def history_stats(history: list[dict], bill_month: str | None, units_consumed: Any) -> dict | None:
    previous, current = split_history(history, bill_month, units_consumed)
    if not previous and not current:
        return None
    all_bars = previous + ([current] if current else [])

    def summarize(bars: list[dict]) -> dict | None:
        if not bars:
            return None
        vals = [b["units"] for b in bars]
        hi = max(bars, key=lambda b: b["units"])
        lo = min(bars, key=lambda b: b["units"])
        return {
            "count": len(vals),
            "total": _r(sum(vals)),
            "mean": _r(statistics.mean(vals)),
            "median": _r(statistics.median(vals)),
            "highest": {"month": hi.get("month"), "units": hi["units"]},
            "lowest": {"month": lo.get("month"), "units": lo["units"]},
            "months_above": {str(t): sum(v > t for v in vals) for t in THRESHOLDS},
            "months_at_or_above": {str(t): sum(v >= t for v in vals) for t in THRESHOLDS},
        }

    changes = []
    for a, b in zip(all_bars, all_bars[1:]):
        pct = _r((b["units"] - a["units"]) / a["units"] * 100) if a["units"] else None
        changes.append({"from": a.get("month"), "to": b.get("month"), "change_units": _r(b["units"] - a["units"]), "change_pct": pct})

    out: dict[str, Any] = {
        "note": "bars are oldest->newest; 'previous_months' excludes the current month's bar",
        "previous_months_list": previous,
        "current_month_bar": current,
        "previous_months_stats": summarize(previous),
        "including_current_stats": summarize(all_bars),
        "month_over_month": changes,
    }
    cur_units = current["units"] if current else (units_consumed if _num(units_consumed) else None)
    prev_stats = out["previous_months_stats"]
    if cur_units is not None and prev_stats and prev_stats["mean"]:
        out["current_vs_previous_mean"] = {
            "current_units": cur_units,
            "previous_mean": prev_stats["mean"],
            "difference_units": _r(cur_units - prev_stats["mean"]),
            "difference_pct": _r((cur_units - prev_stats["mean"]) / prev_stats["mean"] * 100),
        }
    return out


def bill_stats(bill: dict | None) -> dict:
    if not bill:
        return {}
    out: dict[str, Any] = {}
    cur, units = bill.get("current_bill"), bill.get("units_consumed")

    by_type: dict[str, float] = {}
    for c in bill.get("charges") or []:
        by_type[c["type"]] = round(by_type.get(c["type"], 0) + c["amount"], 2)
    tax_by_type: dict[str, float] = {}
    for t in bill.get("taxes") or []:
        tax_by_type[t["type"]] = round(tax_by_type.get(t["type"], 0) + t["amount"], 2)
    out["charges_by_type"] = by_type
    out["taxes_by_type"] = tax_by_type
    out["sum_of_charge_lines"] = _r(sum(by_type.values())) if by_type else None
    out["sum_of_tax_lines"] = _r(sum(tax_by_type.values())) if tax_by_type else None

    if _num(cur) and cur:
        if _num(bill.get("total_taxes")):
            out["taxes_share_of_current_bill_pct"] = _r(bill["total_taxes"] / cur * 100)
        if _num(bill.get("total_charges")):
            out["charges_share_of_current_bill_pct"] = _r(bill["total_charges"] / cur * 100)
        out["line_share_of_current_bill_pct"] = {
            "charges": {k: _r(v / cur * 100) for k, v in by_type.items()},
            "taxes": {k: _r(v / cur * 100) for k, v in tax_by_type.items()},
        }
    if _num(cur) and _num(units) and units:
        out["current_bill_per_unit"] = _r(cur / units)
        if "energy" in by_type:
            out["energy_charges_per_unit"] = _r(by_type["energy"] / units)
    if _num(bill.get("payable_within_due_date")) and _num(bill.get("payable_after_due_date")):
        late = bill["payable_after_due_date"] - bill["payable_within_due_date"]
        out["late_payment_extra_amount"] = _r(late)
        if bill["payable_within_due_date"]:
            out["late_payment_extra_pct"] = _r(late / bill["payable_within_due_date"] * 100)
    if _num(bill.get("previous_reading")) and _num(bill.get("current_reading")):
        out["reading_difference"] = _r(bill["current_reading"] - bill["previous_reading"])
    return out


def compute_all(bill: dict | None, facts: dict) -> dict:
    """Everything the answering step may need, computed once in Python."""
    result: dict[str, Any] = {"bill": bill_stats(bill)}
    hist = facts.get("usage_history") or []
    if hist:
        result["usage_history"] = history_stats(hist, (bill or {}).get("bill_month"), (bill or {}).get("units_consumed"))
    return result
