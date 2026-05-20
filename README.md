This project is inspired by this paper: https://www.mdpi.com/2076-3417/16/1/416

=====

Ender — A Minimal Bug Tracker with Automated Duplicate Detection
-----------------------------------------------------------------

Abstract
--------
Ender is a compact, self-contained bug-tracking prototype implemented in Python/Flask with an
SQLite backend. It demonstrates an approachable pipeline for detecting duplicate bug reports
using semantic embeddings (when a Hugging Face embedding model is available) and a robust
fallback fuzzy-matching strategy. The repository is intended as both a pragmatic tool for small
projects and a didactic codebase for experimentation with duplicate-detection methods.

Introduction
------------
This project provides an end-to-end minimal issue tracker that supports bug creation, commenting,
status transitions, and duplicate detection. The goals are: clarity, reproducibility, and a small
surface area for experimentation. The user-facing UI is implemented with Jinja2 templates and a
calm futuristic theme. Administrative operations (status updates, clearing seeded data) are
protected by a simple token header.

Key Capabilities
-----------------
- Create bug records with `title`, `description`, `severity` and optional `source` metadata.
- View and comment on individual bugs.
- Server-side search and filter on `title`, `description`, `status`, and `severity`.
- Automatic duplicate detection at bug creation and while seeding public data.
- Manual duplicate flagging by administrators.

Frameworks and Dependencies
---------------------------
- Python 3.10+ (tested on 3.11)
- Flask — routing and templating
- SQLite (builtin) — single-file database for persistence
- requests — HTTP client for optional Bugzilla seeding and Hugging Face API
- rapidfuzz — lightweight fuzzy string matching fallback

The project includes a minimal `requirements.txt` that lists these packages.

Repository Structure
--------------------
- `app.py`: the single-module Flask application and data-access functions.
- `templates/`: Jinja2 templates used by the UI (`base.html`, `index.html`, `bugs.html`, `bug.html`, `report.html`).
- `requirements.txt`: Python dependencies.
- `bugs.db`: SQLite database file (generated at runtime).

Design and Implementation Details
---------------------------------

Database schema
~~~~~~~~~~~~~~~
The `bugs` table stores the primary issue record and includes the following columns:

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `title` TEXT NOT NULL
- `description` TEXT NOT NULL
- `status` TEXT NOT NULL DEFAULT 'open'
- `severity` TEXT NOT NULL DEFAULT 'low'  (one of `low`, `medium`, `high`, `critical`)
- `created_at` TEXT ISO-8601 timestamp
- `duplicate_of` INTEGER nullable; references `bugs(id)` when a bug is marked duplicate
- `source` TEXT NOT NULL DEFAULT 'manual' (used to mark records seeded from Bugzilla)

There is a `comments` table that references `bug_id` and stores `author`, `text`, and `created_at`.

HTTP API and Routes
-------------------
Major routes and API endpoints are implemented in `app.py`. Highlights:

- `GET /` — Landing page showing recent bugs.
- `GET /bugs` — Bug list with server-side filters: query params `q`, `status`, `severity`.
- `GET /bug/<id>` — Bug detail page (includes comments and admin panel).
- `GET /report-bug` — Form page to file a new bug.
- `POST /api/bugs` — Create a new bug (JSON). Automatic duplicate detection runs here and the
  response includes a `duplicates` list when matches are found.
- `POST /api/bugs/<id>/comment` — Add comment to a bug.
- `POST /api/bugs/<id>/status` — Admin-only status update (requires `X-ADMIN-TOKEN` header).
- `POST /seed/bugzilla` — Seed public Bugzilla bugs (optional host/product/limit JSON body).
- `POST /seed/bugzilla/delete` — Delete seeded bugs (admin/permission implicit via manual use).
- `POST /api/bugs/clear` — Admin-only wipe of all bugs and comments (requires `X-ADMIN-TOKEN`).

Duplicate detection methodology
-------------------------------
The duplicate detection pipeline is intentionally multilayered to be both effective and
operational in air-gapped or low-dependency contexts.

1. Semantic embeddings (preferred):
   - If the environment variable `HUGGINGFACE_API_TOKEN` is set, the system calls the Hugging
     Face inference API (model configurable by `HUGGINGFACE_EMBEDDING_MODEL`) to obtain a
     fixed-size embedding vector for the concatenated `title + '\n' + description` text.
   - The new report's embedding is compared to embeddings of existing bugs (the code currently
     fetches embeddings on-the-fly per comparison). Similarity is measured using cosine similarity.
   - A threshold of 0.8 (cosine) is considered a likely duplicate. Matches above this threshold
     are returned as candidate duplicates.

2. Fallback fuzzy matching (rapidfuzz):
   - If the HF token is not provided or the API fails, the code attempts to use `rapidfuzz`'s
     `token_set_ratio` to calculate a robust token-based similarity score between the new report
     and existing issues.
   - A fuzzy threshold of 80 (out of 100) is used to indicate likely duplication.

3. Heuristic substring fallback:
   - As a last resort, the code falls back to simple substring containment checks to detect
     obvious duplicates (exact or near-exact text copies).

When a duplicate is detected during creation or seeding, the new bug is created with `status='duplicate'`
and `duplicate_of` set to the first matching bug id. The API response also returns the list of
candidate duplicates and their similarity scores so UI clients can present choices to users.

Implementation notes and tradeoffs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Embedding efficiency: the current implementation requests embeddings for each comparison, which is
  simple but inefficient for large datasets. For production use, store and index embeddings (e.g.,
  in a vector DB) and compute nearest neighbors without calling the external API for every pair.
- Threshold tuning: the 0.8 cosine threshold and 80 rapidfuzz threshold are conservative defaults;
  tune them to your corpus characteristics.
- Security: admin actions are protected by a simple static token (`ADMIN_TOKEN` env var). This is
  convenient but not secure for multi-user deployments. Replace with OAuth2/session-based auth
  for production.

Front-end and UX
----------------
The UI uses responsive, semantic Jinja templates in `templates/`:

- `base.html` — theme, layout, CSS, and a simple JS theme toggle.
- `bugs.html` — bug-list with search and filter panel; instant filtering via small debounce.
- `bug.html` — bug detail, comments, and an admin panel with a duplicate target field (visible
  only when marking a bug duplicate).
- `report.html` — new bug form with duplicate candidates previewed when a report is submitted.

Admin features
--------------
- Status updates via `POST /api/bugs/<id>/status` require `X-ADMIN-TOKEN` header.
- Admins can mark a bug as duplicate and provide an explicit `duplicate_of` target.
- A seeded Bugzilla import exists to bootstrap example reports and can be cleared with a
  dedicated endpoint.

Configuration and environment variables
---------------------------------------
- `BUG_DB` — path to SQLite database (defaults to `bugs.db`).
- `ADMIN_TOKEN` — admin header token (default `admin-secret` in dev). Override in production.
- `HUGGINGFACE_API_TOKEN` — optional; if set, enables semantic embedding-based duplicate detection.
- `HUGGINGFACE_EMBEDDING_MODEL` — HF model id for embedding API (default `sentence-transformers/all-MiniLM-L6-v2`).

Development and running
-----------------------
Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.venv\\Scripts\\activate    # Windows PowerShell
pip install -r requirements.txt
```

Start the app (development):

```bash
set ADMIN_TOKEN=my-secret      # Windows CMD
PowerShell: $env:ADMIN_TOKEN = 'my-secret'
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

Testing and verification
------------------------
- Manual: file some test bugs via the UI or `POST /api/bugs` and validate the `duplicates` key.
- Backend: you can call `detect_duplicates(title, description)` interactively to see returned
  candidate lists.

Extensibility and future directions
-----------------------------------
- Persist embeddings: store embeddings alongside bug records to avoid redundant API calls.
- Use a vector index (FAISS, Pinecone, Weaviate) for efficient nearest-neighbor retrieval.
- Improve authentication and add role-based access control for admin functions.
- Add pagination, sorting, and improved UX for large bug lists.

Acknowledgements and references
-------------------------------
This repository was developed as a small demonstration and learning artifact. It borrows ideas
from common duplicate-detection literature and demonstrates a simple hybrid approach combining
semantic and fuzzy techniques.

License
-------
This code is provided under the MIT license. See `LICENSE` for details (not included by default).
