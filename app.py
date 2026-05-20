from flask import Flask, request, jsonify, render_template, redirect, url_for, abort
import os
import sqlite3
from datetime import datetime
import requests
import math


DB_PATH = os.environ.get('BUG_DB', 'bugs.db')
HF_TOKEN = os.environ.get('HUGGINGFACE_API_TOKEN')
HF_MODEL = os.environ.get('HUGGINGFACE_EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'admin-secret')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS bugs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        severity TEXT NOT NULL DEFAULT 'low',
        created_at TEXT NOT NULL,
        duplicate_of INTEGER,
        source TEXT NOT NULL DEFAULT 'manual'
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bug_id INTEGER NOT NULL,
        author TEXT,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(bug_id) REFERENCES bugs(id)
    )
    ''')
    conn.commit()
    conn.close()


def ensure_source_column():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(bugs)")
    columns = [row['name'] for row in cur.fetchall()]
    if 'source' not in columns:
        cur.execute('ALTER TABLE bugs ADD COLUMN source TEXT NOT NULL DEFAULT \'manual\'')
        conn.commit()
    conn.close()


def ensure_duplicate_column():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(bugs)")
    columns = [row['name'] for row in cur.fetchall()]
    if 'duplicate_of' not in columns:
        cur.execute('ALTER TABLE bugs ADD COLUMN duplicate_of INTEGER')
        conn.commit()
    conn.close()


def fetch_all_bugs():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM bugs ORDER BY created_at DESC')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_filtered_bugs(search=None, status=None, severity=None):
    conn = get_db()
    cur = conn.cursor()
    query = 'SELECT b.*, COUNT(c.id) AS comment_count FROM bugs b LEFT JOIN comments c ON c.bug_id = b.id'
    filters = []
    params = []
    if status and status != 'all':
        filters.append('b.status = ?')
        params.append(status)
    if severity and severity != 'all':
        filters.append('b.severity = ?')
        params.append(severity)
    if search:
        term = f'%{search}%'
        filters.append('(b.title LIKE ? OR b.description LIKE ?)')
        params.extend([term, term])
    if filters:
        query += ' WHERE ' + ' AND '.join(filters)
    query += ' GROUP BY b.id ORDER BY b.created_at DESC'
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    bugs = [dict(r) for r in rows]
    for bug in bugs:
        bug['comment_count'] = bug.get('comment_count', 0)
    return bugs


def fetch_bug(bug_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM bugs WHERE id=?', (bug_id,))
    row = cur.fetchone()
    if not row:
        return None
    bug = dict(row)
    cur.execute('SELECT * FROM comments WHERE bug_id=? ORDER BY created_at', (bug_id,))
    bug['comments'] = [dict(r) for r in cur.fetchall()]
    conn.close()
    return bug


def create_bug(title, description, severity, source='manual', status='open', duplicate_of=None):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute('INSERT INTO bugs (title, description, severity, status, created_at, source, duplicate_of) VALUES (?,?,?,?,?,?,?)',
                (title, description, severity, status, now, source, duplicate_of))
    bug_id = cur.lastrowid
    conn.commit()
    conn.close()
    return bug_id


def add_comment(bug_id, author, text):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute('INSERT INTO comments (bug_id, author, text, created_at) VALUES (?,?,?,?)',
                (bug_id, author, text, now))
    conn.commit()
    conn.close()


def update_status(bug_id, status, duplicate_of=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('UPDATE bugs SET status=?, duplicate_of=? WHERE id=?', (status, duplicate_of, bug_id))
    conn.commit()
    conn.close()


def hf_embed(text):
    if not HF_TOKEN:
        return None
    url = f'https://api-inference.huggingface.co/embeddings/{HF_MODEL}'
    headers = {'Authorization': f'Bearer {HF_TOKEN}'}
    try:
        r = requests.post(url, json={"inputs": text}, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get('embedding') or data
    except Exception:
        return None


def cosine(a, b):
    if not a or not b: return 0.0
    num = sum(x*y for x,y in zip(a,b))
    sa = math.sqrt(sum(x*x for x in a))
    sb = math.sqrt(sum(x*x for x in b))
    if sa==0 or sb==0: return 0.0
    return num/(sa*sb)


def detect_duplicates(title, description):
    # Combine title + description
    text = title + '\n' + description
    bugs = fetch_all_bugs()
    candidates = []
    # Try HF embeddings first
    emb = hf_embed(text)
    if emb:
        for b in bugs:
            other = (b['title'] + '\n' + b['description'])
            oemb = hf_embed(other)
            if not oemb:
                continue
            score = cosine(emb, oemb)
            if score >= 0.8:
                candidates.append({'bug': b, 'score': score})
    else:
        # Fallback: simple token overlap / ratio via rapidfuzz if available
        try:
            from rapidfuzz import fuzz
            for b in bugs:
                other = b['title'] + '\n' + b['description']
                score = fuzz.token_set_ratio(text, other)
                if score >= 80:
                    candidates.append({'bug': b, 'score': score/100.0})
        except Exception:
            # Last resort: substring check
            for b in bugs:
                other = b['title'] + '\n' + b['description']
                if text.strip().lower() in other.strip().lower() or other.strip().lower() in text.strip().lower():
                    candidates.append({'bug': b, 'score': 1.0})
    # sort by score desc
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates


app = Flask(__name__)
init_db()
ensure_source_column()
ensure_duplicate_column()


@app.route('/')
def index():
    recent_bugs = fetch_all_bugs()[:5]
    return render_template('index.html', recent_bugs=recent_bugs)


@app.route('/report-bug')
def report_bug():
    return render_template('report.html')


@app.route('/bugs')
def bug_list():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', 'all')
    severity = request.args.get('severity', 'all')
    bugs = fetch_filtered_bugs(search=q, status=status, severity=severity)
    return render_template('bugs.html', bugs=bugs, q=q, status=status, severity=severity)


@app.route('/bug/<int:bug_id>')
def view_bug(bug_id):
    bug = fetch_bug(bug_id)
    if not bug:
        abort(404)
    return render_template('bug.html', bug=bug)


@app.route('/api/bugs', methods=['POST'])
def api_create_bug():
    data = request.get_json() or {}
    title = data.get('title')
    description = data.get('description')
    severity = data.get('severity', 'low')
    if not title or not description:
        return jsonify({'error':'title and description required'}), 400
    dup = detect_duplicates(title, description)
    duplicate_of = dup[0]['bug']['id'] if dup else None
    status = 'duplicate' if dup else 'open'
    bug_id = create_bug(title, description, severity, status=status, duplicate_of=duplicate_of)
    resp = {'id': bug_id, 'duplicates': dup}
    return jsonify(resp), 201


@app.route('/api/bugs/<int:bug_id>/comment', methods=['POST'])
def api_add_comment(bug_id):
    data = request.get_json() or {}
    author = data.get('author', 'anonymous')
    text = data.get('text')
    if not text:
        return jsonify({'error':'text required'}), 400
    if not fetch_bug(bug_id):
        return jsonify({'error':'bug not found'}), 404
    add_comment(bug_id, author, text)
    return jsonify({'ok': True}), 201


@app.route('/api/bugs/<int:bug_id>/status', methods=['POST'])
def api_update_status(bug_id):
    token = request.headers.get('X-ADMIN-TOKEN')
    if token != ADMIN_TOKEN:
        return jsonify({'error':'admin token required'}), 403
    data = request.get_json() or {}
    status = data.get('status')
    duplicate_of = data.get('duplicate_of')
    if status not in ('open','being investigated','fixed','duplicate'):
        return jsonify({'error':'invalid status'}), 400
    bug = fetch_bug(bug_id)
    if not bug:
        return jsonify({'error':'bug not found'}), 404
    if status == 'duplicate':
        if duplicate_of in (None, ''):
            return jsonify({'error':'duplicate_of is required when marking duplicate'}), 400
        try:
            duplicate_of = int(duplicate_of)
        except Exception:
            return jsonify({'error':'duplicate_of must be a valid bug id'}), 400
        if duplicate_of == bug_id:
            return jsonify({'error':'bug cannot be a duplicate of itself'}), 400
        if not fetch_bug(duplicate_of):
            return jsonify({'error':'duplicate target bug not found'}), 404
    else:
        duplicate_of = None
    update_status(bug_id, status, duplicate_of)
    return jsonify({'ok': True})


@app.route('/seed/bugzilla', methods=['POST'])
def seed_bugzilla():
    data = request.get_json() or {}
    host = data.get('host', 'bugzilla.mozilla.org')
    product = data.get('product', 'Firefox')
    limit = int(data.get('limit', 10))
    try:
        url = f'https://{host}/rest/bug'
        params = {'product': product, 'limit': limit, 'include_fields': 'id,summary,severity,priority,creation_time'}
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        bugs = resp.json().get('bugs', [])
    except Exception as e:
        return jsonify({'error': 'failed to fetch from bugzilla', 'detail': str(e)}), 500

    created = []
    for b in bugs:
        bid = b.get('id')
        title = b.get('summary') or f'Bug {bid}'
        # fetch comments to use as description
        desc = ''
        try:
            cr = requests.get(f'https://{host}/rest/bug/{bid}/comment', timeout=20)
            cr.raise_for_status()
            cm = cr.json().get('bugs', {}).get(str(bid), {}).get('comments', [])
            if cm:
                desc = cm[0].get('text','')
        except Exception:
            desc = ''

        sev = (b.get('severity') or b.get('priority') or 'low')
        sev_map = {'blocker': 'critical', 'critical': 'high', 'major': 'high', 'minor': 'medium', 'trivial': 'low', 'enhancement': 'low'}
        sev_mapped = sev_map.get(sev.lower(), 'low') if isinstance(sev, str) else 'low'

        duplicates = detect_duplicates(title, desc)
        duplicate_of = duplicates[0]['bug']['id'] if duplicates else None
        status = 'duplicate' if duplicates else 'open'
        new_id = create_bug(title, desc, sev_mapped, source='bugzilla', status=status, duplicate_of=duplicate_of)
        created.append({'source_id': bid, 'created_id': new_id, 'duplicates': duplicates})

    return jsonify({'ok': True, 'created': created})


@app.route('/seed/bugzilla/delete', methods=['POST'])
def delete_bugzilla_seeded():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM bugs WHERE source = ?", ('bugzilla',))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted': deleted})


@app.route('/api/bugs/clear', methods=['POST'])
def clear_all_bugs():
    token = request.headers.get('X-ADMIN-TOKEN')
    if token != ADMIN_TOKEN:
        return jsonify({'error': 'admin token required'}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM comments')
    cur.execute('DELETE FROM bugs')
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted': deleted})


if __name__ == '__main__':
    app.run(debug=True, port=int(os.environ.get('PORT', 5000)))
