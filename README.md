
# ⚡ Utility Bill Decoder

**An AI-powered application for extracting electricity bill information and answering bill-related questions.**

<p align="center">
  <a href="https://utility-bill-decoder.streamlit.app/">
    <img src="https://img.shields.io/badge/Live%20Demo-Open%20App-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white" alt="Live Demo">
  </a>
  <a href="https://github.com/K-Jeiya/Utility-Bill-Decoder">
    <img src="https://img.shields.io/badge/GitHub-Repository-181717?style=for-the-badge&logo=github" alt="GitHub Repository">
  </a>
</p>

---

## 📌 Overview

Utility Bill Decoder is an AI-powered web application that analyzes electricity bill images and converts the information into structured, understandable outputs.

The project was developed as part of the **Women Tech Quest 2026 — Build with AI** challenge.

## ✨ Features

- 📄 **Bill Image Processing** — Analyze uploaded electricity bill images.
- 🤖 **AI-Powered Extraction** — Extract relevant billing information using Google Gemini.
- 📊 **Structured Outputs** — Organize extracted information into readable results.
- 💬 **Question Answering** — Answer questions about bill details.
- 🧮 **Billing Calculations** — Process consumption, charges, taxes, arrears, and payable amounts.
- 🌐 **Live Demo** — Access the application online through Streamlit.

## 🖥️ Live Demo

**[Launch Utility Bill Decoder →](https://utility-bill-decoder.streamlit.app/)**

Upload a supported electricity bill image to explore the extraction and question-answering features.

> **Note:** The public demo uses sample questions. The private competition dataset is not included in the public repository.

## 🔄 How It Works

1. Upload an electricity bill image.
2. The application processes the image using an AI model.
3. Relevant billing details are extracted.
4. Extracted information is validated and calculated.
5. Results and answers to bill-related questions are displayed.

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Application logic and data processing |
| Google Gemini | AI-powered bill analysis |
| Streamlit | Web application interface |
| Git & GitHub | Version control and source code hosting |
| Streamlit Community Cloud | Application deployment |

## 📂 Project Structure

```text
Utility-Bill-Decoder/
├── source/
│   ├── app.py
│   ├── bill_extractor.py
│   ├── cache.py
│   ├── calculations.py
│   ├── config.py
│   ├── llm_client.py
│   ├── main.py
│   ├── make_submission.py
│   ├── prompts.py
│   ├── question_answerer.py
│   ├── validators.py
│   ├── requirements.txt
│   └── tests/
├── .gitignore
└── README.md
```

## 🚀 Run Locally

### 1. Clone the repository

```bash
git clone https://github.com/K-Jeiya/Utility-Bill-Decoder.git
cd Utility-Bill-Decoder
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
cd source
pip install -r requirements.txt
```

### 4. Configure API credentials

Set up the required Google Gemini API key and model configuration according to the project's configuration requirements.

**Never commit API keys, credentials, or private datasets to GitHub.**

### 5. Run the application

```bash
streamlit run app.py
```

## 🔐 Security & Privacy

- Keep API credentials private.
- Do not upload sensitive personal information to a public demo.
- Keep private competition datasets out of the public repository.

## 👩‍💻 Author

**Jeiya Kumari**

- GitHub: [K-Jeiya](https://github.com/K-Jeiya)
- LinkedIn: [Jeiya Kumari](https://linkedin.com/in/jeiyakumari/)

---

<p align="center">
  Built with Python, AI, and Streamlit.
</p>
