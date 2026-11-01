import datetime
import hmac
import re
import time
from flask import Blueprint, request, jsonify, session, current_app, g
from werkzeug.security import generate_password_hash, check_password_hash
from .db import get_db
from .clientip import client_ip

bp = Blueprint('auth', __name__, url_prefix='/api')

REGISTER_LIMIT = 10
REGISTER_WINDOW = 3600

def get_lockout_key(username):
    return (client_ip(), username.lower())

def is_locked_out(username):
    key = get_lockout_key(username)
    if key in current_app.lockout_data:
        timestamp, count = current_app.lockout_data[key]
        if count >= 5:
            now = datetime.datetime.now(datetime.UTC)
            if now < timestamp + datetime.timedelta(minutes=5):
                return True
            else:
                # Expired lockout
                del current_app.lockout_data[key]
    return False

def record_failed_login(username):
    key = get_lockout_key(username)
    now = datetime.datetime.now(datetime.UTC)
    if key in current_app.lockout_data:
        timestamp, count = current_app.lockout_data[key]
        current_app.lockout_data[key] = [now, count + 1]
    else:
        current_app.lockout_data[key] = [now, 1]

def clear_lockout(username):
    key = get_lockout_key(username)
    current_app.lockout_data.pop(key, None)

def register_hits():
    # Recent counted registration attempts from this client IP, oldest first
    now = time.monotonic()
    hits = current_app.register_rate_data.setdefault(client_ip(), [])
    hits[:] = [t for t in hits if now - t < REGISTER_WINDOW]
    return hits

def enroll_code_ok(data):
    expected = current_app.config.get('ENROLL_CODE')
    if not expected:
        return True
    given = data.get('enroll_code')
    if not isinstance(given, str):
        return False
    return hmac.compare_digest(given.encode('utf-8'), expected.encode('utf-8'))

@bp.route('/register', methods=['POST'])
def register():
    # Accounts created and wrong enrollment codes both count toward 10 per hour per IP
    hits = register_hits()
    if len(hits) >= REGISTER_LIMIT:
        return jsonify({"error": "Too many registrations. Try again later."}), 429

    data = request.get_json()
    if not enroll_code_ok(data):
        hits.append(time.monotonic())
        return jsonify({"error": "Enrollment code required."}), 403
    username = data.get('username', '').lower()
    password = data.get('password', '')
    role = data.get('role', '')

    if not re.match(r'^[a-z0-9_.-]{3,32}$', username):
        return jsonify({"error": "Invalid username format"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password too short"}), 400
    if role not in ['individual', 'manager']:
        return jsonify({"error": "Invalid role"}), 400

    db = get_db()
    try:
        password_hash = generate_password_hash(password, method='scrypt')
        cursor = db.execute(
            "INSERT INTO accounts (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, datetime.datetime.now(datetime.UTC).isoformat())
        )
        db.commit()
        user_id = cursor.lastrowid
    except db.IntegrityError:
        return jsonify({"error": "Username already exists"}), 409
    hits.append(time.monotonic())

    session.clear()
    session['user_id'] = user_id

    return jsonify({
        "id": user_id,
        "username": username,
        "role": role
    }), 201

@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').lower()
    password = data.get('password', '')

    if is_locked_out(username):
        return jsonify({"error": "Too many failed attempts. Try again later."}), 429

    db = get_db()
    user = db.execute(
        "SELECT * FROM accounts WHERE username = ?", (username,)
    ).fetchone()

    if user is None or not check_password_hash(user['password_hash'], password):
        record_failed_login(username)
        return jsonify({"error": "Incorrect username or password."}), 401

    clear_lockout(username)
    session.clear()
    session['user_id'] = user['id']

    return jsonify({
        "id": user['id'],
        "username": user['username'],
        "role": user['role']
    }), 200

@bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return '', 204

@bp.route('/me')
def me():
    user_id = session.get('user_id')
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    user = db.execute(
        "SELECT id, username, role FROM accounts WHERE id = ?", (user_id,)
    ).fetchone()

    if user is None:
        session.clear()
        return jsonify({"error": "Unauthorized"}), 401

    return jsonify({
        "id": user['id'],
        "username": user['username'],
        "role": user['role']
    }), 200

def login_required(f):
    import functools
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        db = get_db()
        g.user = db.execute(
            "SELECT * FROM accounts WHERE id = ?", (session['user_id'],)
        ).fetchone()

        if g.user is None:
            session.clear()
            return jsonify({"error": "Unauthorized"}), 401

        return f(*args, **kwargs)
    return decorated_function
