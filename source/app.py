
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from bill_extractor import extract_bill, expected_provider
from config import PROJECT_ROOT, load_settings
from llm_client import GeminiClient
from question_answerer import answer_questions


st.set_page_config(
    page_title="Utility Bill Decoder",
    page_icon="⚡",
    layout="wide",
)

st.title("⚡ Utility Bill Decoder")
st.caption("AI-powered electricity bill extraction and question answering")

st.markdown("""
Upload an electricity bill image to extract its details, review the
structured JSON, and answer the official bill-related questions.
""")

# Load the official question template without modifying it.
template_path = PROJECT_ROOT / "data" / "test" / "csv" / "level2.csv"


@st.cache_data
def load_official_questions(path_string: str):
    path = Path(path_string)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return []

    first_bill_id = rows[0]["bill_id"]
    return [
        (row["question_id"], row["question"])
        for row in rows
        if row["bill_id"] == first_bill_id
    ]


left, right = st.columns([1, 1])

with left:
    st.subheader("1. Upload your bill")

    provider = st.selectbox(
        "Electricity provider",
        ["IESCO", "KESC", "LESCO"],
    )

    uploaded_file = st.file_uploader(
        "Choose a bill image",
        type=["png", "jpg", "jpeg"],
    )

    if uploaded_file:
        st.image(
            uploaded_file.getvalue(),
            caption=uploaded_file.name,
            use_container_width=True,
        )

with right:
    st.subheader("2. Run extraction")
    st.info(
        "Choose the provider shown on the bill. "
        "Check extracted amounts against the original image."
    )

    run_decoder = st.button(
        "🚀 Run Decoder",
        type="primary",
        use_container_width=True,
        disabled=uploaded_file is None,
    )

if run_decoder and uploaded_file:
    try:
        settings = load_settings()

        image_bytes = uploaded_file.getvalue()
        mime_type = (
            "image/png"
            if uploaded_file.name.lower().endswith(".png")
            else "image/jpeg"
        )

        bill_id = f"{provider}_DEMO"
        client = GeminiClient(settings)

        with st.spinner("Reading bill details with AI..."):
            extraction = extract_bill(
                client,
                bill_id,
                image_bytes,
                mime_type,
                settings.max_output_attempts,
            )

        if extraction.bill is None:
            st.error("Could not extract a valid bill. Try a clearer image.")
            st.stop()

        bill = extraction.bill
        facts = extraction.facts

        st.session_state["demo_bill"] = bill
        st.session_state["demo_bill_id"] = bill_id
        st.session_state["demo_facts"] = facts
        st.session_state["demo_image_name"] = uploaded_file.name
        st.session_state["demo_extract_issues"] = [
            str(issue) for issue in extraction.issues
        ]
        st.session_state.pop("demo_answers", None)
        st.session_state.pop("demo_qa_issues", None)

        questions = load_official_questions(str(template_path))

        if not questions:
            st.warning(
                "Official questions template is unavailable. "
                "Only Level 1 extraction is shown."
            )
        else:
            with st.spinner("Answering bill-related questions..."):
                answers, qa_issues = answer_questions(
                    client,
                    bill_id,
                    image_bytes,
                    mime_type,
                    bill,
                    facts,
                    questions,
                    settings.max_output_attempts,
                )

            st.session_state["demo_questions"] = questions
            st.session_state["demo_answers"] = answers
            st.session_state["demo_qa_issues"] = [
                str(issue) for issue in qa_issues
            ]

        st.success("Bill processing finished.")

    except Exception as exc:
        st.error(f"Processing failed: {exc}")
        st.caption(
            "Check your .env configuration, API connection, "
            "and image format. Do not share your API key."
        )


# Show the latest demo result. These downloads are separate from official files.
if "demo_bill" in st.session_state:
    bill = st.session_state["demo_bill"]
    bill_id = st.session_state["demo_bill_id"]
    bill_json = json.dumps(
        bill,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    st.divider()
    st.subheader("📋 Level 1 — Extracted bill details")

    m1, m2, m3 = st.columns(3)
    m1.metric("Provider", str(bill.get("provider") or "Unknown"))
    m2.metric("Bill month", str(bill.get("bill_month") or "Unknown"))
    m3.metric(
        "Payable amount",
        str(bill.get("payable_within_due_date") or "Unknown"),
    )

    with st.expander("View complete extracted JSON", expanded=True):
        st.json(bill)

    st.download_button(
        "⬇️ Download Level 1 JSON",
        data=json.dumps(bill, indent=2, ensure_ascii=False),
        file_name=f"{bill_id}_level1.json",
        mime="application/json",
    )

    l1_csv = io.StringIO()
    writer = csv.DictWriter(l1_csv, fieldnames=["bill_id", "json"])
    writer.writeheader()
    writer.writerow({"bill_id": bill_id, "json": bill_json})

    st.download_button(
        "⬇️ Download Level 1 CSV",
        data=l1_csv.getvalue().encode("utf-8"),
        file_name=f"{bill_id}_level1.csv",
        mime="text/csv",
    )

    st.subheader("💬 Level 2 — Question answers")

    questions = st.session_state.get("demo_questions", [])
    answers = st.session_state.get("demo_answers", {})

    if questions:
        qa_rows = [
            {
                "bill_id": bill_id,
                "question_id": qid,
                "question": question,
                "answer": answers.get(qid, ""),
            }
            for qid, question in questions
        ]

        st.dataframe(
            pd.DataFrame(qa_rows),
            use_container_width=True,
            hide_index=True,
        )

        qa_csv = io.StringIO()
        writer = csv.DictWriter(
            qa_csv,
            fieldnames=[
                "bill_id", "question_id", "question", "answer"
            ],
        )
        writer.writeheader()
        writer.writerows(qa_rows)

        st.download_button(
            "⬇️ Download Level 2 CSV",
            data=qa_csv.getvalue().encode("utf-8"),
            file_name=f"{bill_id}_level2.csv",
            mime="text/csv",
        )
    else:
        st.warning("No question-answer results are available.")

    issues = (
        st.session_state.get("demo_extract_issues", [])
        + st.session_state.get("demo_qa_issues", [])
    )

    if issues:
        with st.expander(f"Review validation notes ({len(issues)})"):
            for issue in issues:
                st.write(f"- {issue}")

    st.caption(
        "Demo results only. Official competition CSVs are not modified "
        "by this UI."
    )
