# Utility Bill Decoder (WTQ Build Track)

Reads K-Electric (KE), LESCO and IESCO electricity-bill images and produces
**Level 1** (structured JSON per bill) and **Level 2** (plain-English answers to the official questions).

**Python version: 3.12** (3.11+ works). Tested on the logic level with offline unit tests; see "Testing status".

## How it works

1. **Level 1 + extra facts (1 request per bill)** - the original image goes to a vision model
   (`gemini-3.1-flash-lite` by default). It returns the schema JSON plus extra printed facts
   (monthly usage history, billing history, late-payment amounts, printed % split, message board).
2. **Python validation/normalisation** - strict schema check, safe repairs only (fences, trailing commas,
   `"1,234"` -> number, date formats), zero lines dropped, categories checked. Printed amounts are never
   recalculated or rounded. Bad output triggers a limited retry with the specific problem fed back;
   if printed totals don't add up the bill is re-read **once**. Anything still suspicious stays as a warning.
3. **Python arithmetic** (`calculations.py`) - tax share, per-type sums, history average/median/max/min,
   "months above N units", month-over-month change, late-payment extra, etc.
4. **Level 2 (1 request per bill for all 12 questions)** - image + validated JSON + computed numbers + the exact
   official questions. Each question id is validated separately (non-empty, English, no identifiers);
   only missing/bad ids are re-requested. A failed answer is left empty and reported - never made up.
5. **CSV writing** with Python's `csv` module (UTF-8, correct escaping, one-line JSON), the templates are
   never modified, then **validation of the files on disk** and a report.

Other features: result cache (re-runs don't repeat successful calls), rate-limit throttling with
exponential backoff, API key masking, separate run log and error log, `--check-model`.

## Project structure

```
utility-bill-decoder/
  source/                 <- open THIS folder in VS Code
    main.py               CLI / orchestration
    bill_extractor.py     Level 1 extraction + retries
    question_answerer.py  Level 2 answers + per-question validation
    calculations.py       arithmetic done in Python
    validators.py         normalisation, schema/consistency checks, CSV validation, report
    llm_client.py         Gemini SDK wrapper (image input, throttling, retries)
    prompts.py            all prompt text
    config.py             .env loading, approved-model check
    cache.py              result cache
    make_submission.py    builds + checks the submission ZIP
    tests/                offline tests (stubbed model)
    requirements.txt  .env.example  README.md
  data/train/bills/       5 training images (download)
  data/test/bills/        10 test images (download at 12:30)
  data/test/csv/          official level1.csv + level2.csv templates (download, never edited)
  output/                 level1.csv, level2.csv (generated)
  reports/                validation reports (generated)
  logs/                   run logs, errors.log, cache (generated, not submitted)
  demo/                   demo.mp4 (optional) + recording notes
```

## Setup (Windows 11, PowerShell)

```powershell
cd path\to\utility-bill-decoder\source
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env        # replace your-api-key-here with YOUR OWN key (never share or submit .env)
```

If activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again.

Get a free key at <https://aistudio.google.com> (Get API key). `.env` holds `MODEL_PROVIDER=google`,
`MODEL_NAME=gemini-3.1-flash-lite` (or `gemini-3.5-flash-lite`) and `API_KEY`.

## Run

```powershell
# 1. Confirm key + exact model ID work (do this first)
python main.py --check-model

# 2. Offline logic tests (no key needed)
python -m unittest discover -s tests -v

# 3. Training bills (put the 5 images in ..\data\train\bills). Level 1 only, or add the guide's 2 sample questions:
python main.py --mode train --show
python main.py --mode train --demo-questions --show      # writes ..\output_train\

# 4. Test bills with the official templates in ..\data\test\csv  -> writes ..\output\level1.csv and level2.csv
python main.py --mode test

# One bill only (for the demo; writes to ..\output_partial)
python main.py --mode test --only KESC_0002 --show

# Re-validate existing outputs without calling the API
python main.py --mode test --validate-only

# Build the ZIP (checks required files, secrets, 15 MB limit)
python make_submission.py
```

Custom folders: `--bills-dir`, `--level1-template`, `--level2-template`, `--out-dir`.
Use `--no-cache` to force fresh model calls.

## Outputs

* `output\level1.csv` - `bill_id,json` (10 rows, official order, one-line JSON)
* `output\level2.csv` - `bill_id,question_id,question,answer` (120 rows, official order)
* `reports\validation_report_test.md` - fatal errors vs warnings; `logs\errors.log` - problems during the run
* Exit code: 0 = no fatal errors, 1 = fatal validation errors (do not submit), 2 = setup/config problem.

## Known limitations

* Accuracy depends on the model reading the image; validation catches malformed or implausible output but
  **cannot prove values are correct**. Review warnings and spot-check several bills against the images.
* Usage-history bars are small; the month labels and bar values may be misread. History-based answers are only
  as good as that reading (the model is told to say so when a value is unreadable).
* Only the Google (Gemini) client is implemented. Other approved models are rejected, not substituted.
* No local OCR and no deskewing are used; tilt is handled by the vision model. Very large images are downscaled to 3000 px.
* If a bill or question still fails after the retry limits, its cell stays empty, tTesting status
  and nothing is invented. Re-running reuses cached successes.
* Temperature defaults to the model default (set `TEMPERATURE` in `.env` to override).
* A Streamlit UI is available in app.py. Run streamlit run app.py from the source directory. The command-line workflow is also available through main.py.

## Testing status

* Offline unit and end-to-end tests use a stubbed model to check validation, normalisation, arithmetic, retry logic, CSV round-trip, and the guide's KESC_0008 JSON validation.
* The Streamlit interface was tested locally using a sample electricity bill and the configured Google Gemini API.
* The sample extraction returned structured output and a validation warning. Extracted values should be checked against the original bill because successful extraction does not guarantee complete accuracy.

## AI usage

**Coding assistants (used to write this code):** Claude (Anthropic chat assistant). *Add any other tools you used.*

**Runtime models called by the submitted code:** Google `gemini-3.1-flash-lite` via the Google Gen AI SDK
(Google AI Studio API) - or the `MODEL_NAME` set in `.env.example`. No other LLM is called.

**Other services/libraries:** `google-genai`, `python-dotenv`, `Pillow` (image loading/resizing). Python's standard library for CSV/JSON/maths.

**Prohibited services:** Azure services, AWS Textract AnalyzeExpense, Mindee and any invoice/receipt extraction agent
are **not** used. No OCR engine is used.
## Testing status

- Offline unit and end-to-end tests use a stubbed model to check validation, normalisation, arithmetic, retry logic, and CSV handling.
- The Streamlit interface was run locally and tested with a sample electricity bill using the configured Gemini API.
- The sample extraction returned structured output and a validation warning. Extracted values should be checked against the original bill; successful extraction does not guarantee complete accuracy.
- A full test suite and broader real-world accuracy evaluation should be run before production use.
