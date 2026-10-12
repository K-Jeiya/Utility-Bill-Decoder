# Utility Bill Decoder

An AI-powered application that extracts information from electricity bill images and answers bill-related questions.

Built for the Women Tech Quest 2026 Build with AI challenge, with additional improvements to the interactive application.

## Features

- Supports K-Electric (KE), LESCO and IESCO electricity-bill images.
- Extracts bill information into structured JSON.
- Answers bill-related questions using extracted information.
- Validates extracted data and flags potential inconsistencies.
- Provides an interactive Streamlit web interface.
- Supports a command-line workflow for processing bills.
- Uses Google Gemini for vision-based extraction and question answering.

## Tech Stack

- Python 3.12
- Google Gemini API
- Streamlit
- Pandas
- Pillow
- Python CSV and JSON libraries

## Project Structure

- `source/app.py` — Streamlit web interface
- `source/main.py` — command-line workflow
- `source/bill_extractor.py` — bill information extraction
- `source/question_answerer.py` — bill-related question answering
- `source/calculations.py` — calculations derived from extracted data
- `source/validators.py` — data validation and normalisation
- `source/llm_client.py` — Gemini API integration
- `source/tests/` — offline automated tests
- `source/requirements.txt` — Python dependencies
- `source/README.md` — detailed setup and usage instructions

## Run Locally

Python 3.12 is recommended.

1. Clone this repository.
2. Open a terminal in the `source` directory.
3. Create and activate a virtual environment.
4. Install the dependencies:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt