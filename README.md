# EKL Agent

Reads a git repository, maps requirements from a CSV to EKL files using Gemini,
writes the changes, and commits — no crewai, no LiteLLM, no Vertex AI.

## Files

```
ekl_agent/
├── main.py          # Entry point — CLI args and validation
├── agent.py         # All logic — Gemini calls, file I/O, git commit
└── requirements.txt # One dependency: google-generativeai
```

## Setup

```powershell
# Create venv with Python 3.13
pyenv local 3.13.0
python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

$env:GEMINI_API_KEY = "your-key-here"
```

## Run

```powershell
python main.py `
  --repo "C:\path\to\ekl-repo" `
  --csv  ".\requirements.csv" `
  --commit-message "feat: apply EKL requirements"
```

## Dry run (no files written, no commit)

```powershell
python main.py --repo "..." --csv "..." --dry-run
```

## CSV format

Any CSV with at minimum an `id` and `description` column. No `file` or `action`
column needed — Gemini figures out which files to change from the repo structure.

Optional columns used if present: `priority`, `acceptance criteria`, `dependency`.

## How it works

```
STEP 1  Python walks the repo and builds a real file listing
STEP 2  Python reads the CSV requirements
STEP 3  Gemini maps each requirement → file(s) to change + action (MODIFY/CREATE)
STEP 4  For each planned change, Gemini generates the EKL code → Python writes to disk
STEP 5  Python runs git add -A && git commit
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | ✅ | — | Google AI Studio API key |
| `GEMINI_MODEL` | optional | `gemini-2.0-flash` | Model to use |
