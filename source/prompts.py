"""All prompt text lives here so it is easy to review and tune."""
from __future__ import annotations

import json

SCHEMA_TEXT = """{
  "provider": "KE" | "LESCO" | "IESCO",
  "tariff": string | null,                 // tariff code exactly as printed, e.g. "A1-R" or "A-1a(01)"
  "sanctioned_load_kw": number | null,     // labelled Sanc Load / S.Load / San Load
  "bill_month": "YYYY-MM" | null,
  "reading_date": "YYYY-MM-DD" | null,
  "issue_date": "YYYY-MM-DD" | null,
  "due_date": "YYYY-MM-DD" | null,         // last date to pay WITHOUT late-payment surcharge
  "previous_reading": number | null,
  "current_reading": number | null,
  "units_consumed": number | null,         // units billed for the CURRENT month
  "charges": [ {"type": "energy|fixed|fpa|quarterly_adjustment|surcharge|meter_rent|subsidy|other", "amount": number} ],
  "total_charges": number | null,          // printed charges subtotal
  "taxes": [ {"type": "gst|electricity_duty|income_tax|municipal_tax|other_tax", "amount": number} ],
  "total_taxes": number | null,            // printed tax subtotal
  "current_bill": number | null,           // printed amount for this month's bill
  "arrears": number | null,                // previous dues carried forward, keep printed sign
  "payable_within_due_date": number | null,
  "payable_after_due_date": number | null  // HIGHEST late-payment amount if several are printed
}"""

# Format reference taken from the competition guide (training bill KESC_0008).
# It belongs to a DIFFERENT bill than the one being read; values must never be copied.
EXAMPLE_JSON = ('{"provider":"KE","tariff":"A1-R","sanctioned_load_kw":3,"bill_month":"2026-04",'
                '"reading_date":"2026-04-03","issue_date":"2026-04-07","due_date":"2026-04-21",'
                '"previous_reading":8819,"current_reading":8970,"units_consumed":151,"charges":['
                '{"type":"fixed","amount":900},{"type":"energy","amount":1054},{"type":"energy","amount":663.51},'
                '{"type":"quarterly_adjustment","amount":52.91},{"type":"fpa","amount":125.27},'
                '{"type":"surcharge","amount":64.93}],"total_charges":2860.62,"taxes":['
                '{"type":"electricity_duty","amount":29.41},{"type":"gst","amount":520.21},'
                '{"type":"municipal_tax","amount":20}],"total_taxes":569.62,"current_bill":3430.24,'
                '"arrears":-0.53,"payable_within_due_date":3430,"payable_after_due_date":3716}')

EXTRACTION_RULES = """
You are reading ONE Pakistani electricity bill image (K-Electric, LESCO or IESCO). It may be tilted,
photographed, partly in Urdu, and personal details are covered by grey boxes. Look at the WHOLE bill
(header, summary boxes, meter-reading table, bill calculation table, usage-history chart, billing history,
message board, tear-off slip), not just the largest text. Prefer the English labels; use Urdu labels only to help.

Return ONE JSON object with exactly two keys: "bill" and "facts".

"bill" must follow this schema (every key present; use null when a value is not printed, blank, covered by a
grey box or unreadable - never guess):
__SCHEMA__

Rules for "bill":
- Values exactly as printed. Do NOT recalculate, round or correct any amount.
- Numbers are JSON numbers (no quotes, no commas, no "Rs."). Credits ("CR", trailing minus, brackets) are negative.
- Dates are YYYY-MM-DD; bill_month is YYYY-MM (e.g. "MAR 2026" -> "2026-03").
- provider: KE for K-Electric (KESC), LESCO, or IESCO.
- charges = one entry per NON-ZERO line in the charges section (the lines that add up to the printed charges subtotal,
  e.g. "Electricity Charges"). Keep repeated types as separate entries (e.g. two energy slabs). Skip blank and zero lines.
  Do NOT put subtotals, opening balance, previous dues, payments/adjustments, or late-payment-surcharge (LPS) rows in charges.
- Charge types: energy (cost of units, variable slabs, energy charges), fixed (fixed charges), fpa (fuel price adjustment;
  use fpa for both FPA and FCA), quarterly_adjustment (QTA / uniform quarterly adjustment), surcharge (additional
  surcharge, F.C surcharge), meter_rent (meter or service rent), subsidy (government subsidy/relief - record NEGATIVE),
  other (any other charge line).
- taxes = one entry per non-zero line in the tax/government/duties section. Decide charge-vs-tax by the PRINTED SECTION,
  not by the line's name. Tax types: gst (sales tax/GST incl. GST on FPA), electricity_duty (ED), income_tax,
  municipal_tax (municipal/local charges under taxes, e.g. KE MUCT/KMC), other_tax (extra tax, further tax, TV fee, etc.).
  If only a combined tax amount is printed, use taxes = [] and put that amount in total_taxes.
- total_charges / total_taxes: only the printed subtotals; null if none printed. Never invent a subtotal.
- units_consumed is the current month's billed units, not a history value.
- previous_reading / current_reading come from the meter-reading table for the current month.
- arrears: previous dues carried forward with the printed sign; null if blank.
- payable_after_due_date: the highest printed late-payment amount.
- NEVER output names, addresses, CNIC, account/reference/consumer/contract/invoice numbers or meter numbers.

"facts" holds extra printed information used later to answer customer questions:
{
  "usage_history": [ {"month": "YYYY-MM" | null, "units": number} ],   // every bar of the monthly usage chart, OLDEST first, including the
                                                                       // current month's bar if shown. Use the printed bar value. month from the axis labels.
  "billing_history": [ {"month": "YYYY-MM" | null, "billed_amount": number | null, "payment_date": "YYYY-MM-DD" | null, "paid_amount": number | null} ],
  "late_payment_amounts": [ {"description": string, "amount": number} ],  // every printed late-payment/LPS total with its date range
  "printed_percent_split": [ {"label": string, "percent": number} ],     // e.g. energy vs taxes percentage printed at the bottom
  "message_board_text": string | null,                                    // English translation/summary of the message board, no personal data
  "notes": string | null                                                  // anything unreadable/covered/uncertain that you want to flag
}
Use [] / null when the bill has no such information. Never invent history values.

Output strictly valid JSON only: no Markdown fences, no commentary.

For FORMAT reference only, here is the "bill" object for a DIFFERENT bill (do not copy its values):
__EXAMPLE__
"""


def build_extraction_prompt(feedback: str | None = None) -> str:
    text = EXTRACTION_RULES.replace("__SCHEMA__", SCHEMA_TEXT).replace("__EXAMPLE__", EXAMPLE_JSON)
    if feedback:
        text += ("\nYour previous attempt for this same image had problems. Re-read the image carefully and "
                 "return a corrected full response. Only change a value if the image supports it; if the printed "
                 "values genuinely do not add up, keep the printed values.\nProblems:\n" + feedback + "\n")
    return text


QA_RULES = """
You answer customer questions about ONE electricity bill. The bill image is attached. Below you also get structured data
already read from this bill and numbers pre-computed in Python.

Rules:
1. Answer every question in English (even where the bill is in Urdu), using ONLY this bill. No outside tariff/rate knowledge.
2. Numbers must be right. For any arithmetic, count, average, difference or percentage use the COMPUTED values below when
   they apply. If you must compute something else, show the short calculation and double-check it.
3. Re-check the image when a value matters (usage-history bars, line items, dates). If the data below conflicts with the
   image, trust the image and say so briefly.
4. If the bill does not show what is needed, say so plainly instead of guessing.
5. Label estimates with the word "estimate" and explain how it was calculated from bill values.
6. If a question has more than one reasonable meaning, state the interpretation you used or answer both briefly.
7. Never include names, addresses, CNIC, account/reference/consumer/contract/invoice/meter numbers.
8. Be specific and concise (usually 1-4 sentences): give the key number(s) with units/PKR, the month names for history
   questions, and the relevant line items. Amounts are PKR. Do not mention "JSON" or "computed facts" - write for a customer.
9. Answer each question independently using its exact wording. Do not skip any question id.

Output strictly valid JSON only (no Markdown fences): {"answers": {"<question_id>": "<answer text>", ...}}
containing exactly the question ids listed below.
"""


def build_qa_prompt(bill: dict | None, facts: dict, computed: dict,
                    questions: list[tuple[str, str]], feedback: str | None = None) -> str:
    parts = [QA_RULES]
    if bill is None:
        parts.append("NOTE: structured extraction of this bill failed; rely on the image only.\n")
    else:
        parts.append("STRUCTURED BILL DATA (read from this bill):\n" + json.dumps(bill, ensure_ascii=False))
    if facts:
        parts.append("OTHER PRINTED FACTS (usage history, billing history, late-payment amounts, message board):\n"
                     + json.dumps(facts, ensure_ascii=False))
    if computed:
        parts.append("COMPUTED IN PYTHON (authoritative for arithmetic):\n" + json.dumps(computed, ensure_ascii=False))
    parts.append("QUESTIONS:\n" + "\n".join(f"{qid}: {text}" for qid, text in questions))
    if feedback:
        parts.append("Your previous attempt had problems; fix them in this response:\n" + feedback)
    return "\n\n".join(parts)
