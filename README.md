# Simple Bug Tracker with Duplicate Detection

This is a small Flask app that implements a bug tracker with duplicate detection inspired by the linked paper.

Features:
- Create bugs with title, description, severity
- View bug page with comments
- Admin-only status updates (header `X-ADMIN-TOKEN`)
- Duplicate detection: uses Hugging Face embeddings if `HUGGINGFACE_API_TOKEN` is set, otherwise falls back to `rapidfuzz` fuzzy matching

Quick start:

1. Create a virtualenv and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. (Optional) Set `HUGGINGFACE_API_TOKEN` env var to enable embeddings.

3. Run the app:

```powershell
#$env:ADMIN_TOKEN = 'my-secret'
python app.py
```

Open http://127.0.0.1:5000
