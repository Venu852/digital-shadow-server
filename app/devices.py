import datetime
import functools
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from flask import Blueprint, request, jsonify, current_app, g
from werkzeug.security import check_password_hash
from .db import get_db
from .auth import login_required, is_locked_out, record_failed_login, clear_lockout
from .rules import SIGNAL_KEYS
from .sharing import LEVELS, get_sharing, set_sharing

bp = Blueprint('devices', __name__, url_prefix='/api')

# Endpoints authenticated by device token; exempt from the X-Requested-With check
TOKEN_ENDPOINTS = {
    'devices.pair',
    'devices.device_me',
    'devices.device_sharing',
    'devices.upload_day',
    'devices.delete_device_data',
}

MAX_BODY = 4096
RATE_LIMIT = 300
RATE_WINDOW = 3600
LEVEL_KEYS = set(SIGNAL_KEYS)
REQUIRED_KEYS = {'drift', 'levels', 'confidence', 'baseline'}
OPTIONAL_KEYS = {'forecast', 'unusual_hours', 'tz'}
DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
TZ_RE = re.compile(r'^[+-](0\d|1[0-4]):[0-5]\d$')

def now_iso():
    return datetime.datetime.now(datetime.UTC).isoformat()

def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def individual_required(f):
    @functools.wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if g.user['role'] != 'individual':
            return jsonify({"error": "Only individuals can manage devices"}), 403
        return f(*args, **kwargs)
    return decorated_function

def is_rate_limited(device_id):
    now = time.monotonic()
    hits = current_app.device_rate_data.setdefault(device_id, [])
    hits[:] = [t for t in hits if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    return False

def token_required(f):
    # Never reads the session cookie: identity comes only from the bearer token
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer ') or not header[7:].strip():
            return jsonify({"error": "Unauthorized"}), 401

        token_hash = hash_token(header[7:].strip())
        db = get_db()
        device = db.execute(
            "SELECT * FROM devices WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if (device is None
                or not hmac.compare_digest(device['token_hash'], token_hash)
                or device['revoked_at'] is not None):
            return jsonify({"error": "Unauthorized"}), 401

        if is_rate_limited(device['id']):
            return jsonify({"error": "Too many requests"}), 429

        db.execute("UPDATE devices SET last_seen_at = ? WHERE id = ?", (now_iso(), device['id']))
        db.commit()
        g.device = device
        return f(*args, **kwargs)
    return decorated_function

def is_int(value, lo, hi=None):
    # bool is a subclass of int in Python; reject it explicitly
    if type(value) is not int:
        return False
    return value >= lo and (hi is None or value <= hi)

def validate_day(day):
    if not DAY_RE.match(day):
        return None
    try:
        parsed = datetime.date.fromisoformat(day)
    except ValueError:
        return None
    today = datetime.datetime.now(datetime.UTC).date()
    if parsed > today + datetime.timedelta(days=1):
        return None
    if parsed < today - datetime.timedelta(days=400):
        return None
    return parsed

def validate_summary(data):
    """Returns an error message, or None if the summary is valid."""
    if not isinstance(data, dict):
        return "Body must be a JSON object"
    keys = set(data)
    if not REQUIRED_KEYS <= keys:
        return "Missing required field"
    if keys - REQUIRED_KEYS - OPTIONAL_KEYS:
        return "Unknown field"

    if not is_int(data['drift'], 0, 100):
        return "drift must be an integer 0-100"
    levels = data['levels']
    if not isinstance(levels, dict) or set(levels) != LEVEL_KEYS:
        return "levels must have exactly: " + ", ".join(SIGNAL_KEYS)
    if not all(is_int(v, 0, 100) for v in levels.values()):
        return "levels must be integers 0-100"
    if not is_int(data['confidence'], 0, 100):
        return "confidence must be an integer 0-100"
    if data['baseline'] not in ('calibrating', 'established'):
        return "baseline must be 'calibrating' or 'established'"

    if 'forecast' in data:
        forecast = data['forecast']
        if (not isinstance(forecast, dict)
                or set(forecast) != {'screen_min', 'usual_min'}
                or not all(is_int(v, 0) for v in forecast.values())):
            return "forecast must be {screen_min, usual_min} as integers >= 0"
    if 'unusual_hours' in data:
        hours = data['unusual_hours']
        if (not isinstance(hours, list)
                or len(hours) > 24
                or not all(is_int(h, 0, 23) for h in hours)
                or len(set(hours)) != len(hours)):
            return "unusual_hours must be up to 24 distinct integers 0-23"
    if 'tz' in data:
        if not isinstance(data['tz'], str) or not TZ_RE.match(data['tz']):
            return "tz must look like +05:30"
    return None

@bp.route('/devices/pair', methods=['POST'])
def pair():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Body must be a JSON object"}), 400
    username = data.get('username', '')
    password = data.get('password', '')
    device_name = data.get('device_name', '')
    if not all(isinstance(v, str) for v in (username, password, device_name)):
        return jsonify({"error": "Invalid fields"}), 400
    if not (1 <= len(device_name) <= 40):
        return jsonify({"error": "device_name must be 1-40 characters"}), 400
    username = username.lower()

    # Shares the lockout counters with /api/login
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

    if user['role'] != 'individual':
        return jsonify({"error": "Only individuals can pair devices"}), 403

    device_id = uuid.uuid4().hex
    device_token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO devices (id, account_id, name, token_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (device_id, user['id'], device_name, hash_token(device_token), now_iso())
    )
    db.commit()

    # The plain token is returned once and never stored
    return jsonify({"device_id": device_id, "device_token": device_token}), 201

@bp.route('/devices', methods=['GET'])
@individual_required
def list_devices():
    db = get_db()
    devices = db.execute(
        "SELECT id, name, created_at, last_seen_at, revoked_at FROM devices WHERE account_id = ? ORDER BY created_at",
        (g.user['id'],)
    ).fetchall()
    return jsonify([{
        "id": d['id'],
        "name": d['name'],
        "created_at": d['created_at'],
        "last_seen_at": d['last_seen_at'],
        "revoked": d['revoked_at'] is not None,
    } for d in devices]), 200

@bp.route('/devices/<device_id>', methods=['DELETE'])
@individual_required
def revoke_device(device_id):
    db = get_db()
    device = db.execute(
        "SELECT revoked_at FROM devices WHERE id = ? AND account_id = ?",
        (device_id, g.user['id'])
    ).fetchone()
    if device is None:
        return jsonify({"error": "Device not found"}), 404

    if device['revoked_at'] is None:
        db.execute("UPDATE devices SET revoked_at = ? WHERE id = ?", (now_iso(), device_id))
        db.commit()
    return '', 204

@bp.route('/me/data', methods=['DELETE'])
@individual_required
def delete_my_data():
    db = get_db()
    db.execute(
        "DELETE FROM daily_summaries WHERE device_id IN (SELECT id FROM devices WHERE account_id = ?)",
        (g.user['id'],)
    )
    db.commit()
    return '', 204

@bp.route('/device/me', methods=['GET'])
@token_required
def device_me():
    db = get_db()
    account = db.execute(
        "SELECT username FROM accounts WHERE id = ?", (g.device['account_id'],)
    ).fetchone()
    return jsonify({
        "device_id": g.device['id'],
        "username": account['username'],
        "sharing_level": get_sharing(g.device['account_id'])['level'],
    }), 200

@bp.route('/device/sharing', methods=['PUT'])
@token_required
def device_sharing():
    # Same rules as PUT /api/me/sharing, for the device's account
    data = request.get_json(silent=True)
    level = data.get('level') if isinstance(data, dict) else None
    if level not in LEVELS:
        return jsonify({"error": "Invalid sharing level"}), 400
    return jsonify(set_sharing(g.device['account_id'], level)), 200

@bp.route('/device/days/<day>', methods=['PUT'])
@token_required
def upload_day(day):
    if request.content_length is not None and request.content_length > MAX_BODY:
        return jsonify({"error": "Body too large"}), 413
    raw = request.stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        return jsonify({"error": "Body too large"}), 413

    # Nothing is stored unless the account's sharing level allows it
    if get_sharing(g.device['account_id'])['level'] == 'nothing':
        return jsonify({"error": "sharing is off"}), 403

    if validate_day(day) is None:
        return jsonify({"error": "Invalid day"}), 400
    try:
        data = json.loads(raw)
    except ValueError:
        return jsonify({"error": "Body must be valid JSON"}), 400
    error = validate_summary(data)
    if error:
        return jsonify({"error": error}), 400

    db = get_db()
    existing = db.execute(
        "SELECT 1 FROM daily_summaries WHERE device_id = ? AND day = ?",
        (g.device['id'], day)
    ).fetchone()
    forecast = data.get('forecast')
    hours = data.get('unusual_hours')
    db.execute(
        """
        INSERT INTO daily_summaries
            (device_id, day, drift, levels_json, confidence, baseline,
             forecast_json, unusual_hours_json, tz, received_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id, day) DO UPDATE SET
            drift = excluded.drift,
            levels_json = excluded.levels_json,
            confidence = excluded.confidence,
            baseline = excluded.baseline,
            forecast_json = excluded.forecast_json,
            unusual_hours_json = excluded.unusual_hours_json,
            tz = excluded.tz,
            received_at = excluded.received_at
        """,
        (
            g.device['id'], day, data['drift'],
            json.dumps(data['levels'], sort_keys=True),
            data['confidence'], data['baseline'],
            json.dumps(forecast, sort_keys=True) if forecast is not None else None,
            json.dumps(hours) if hours is not None else None,
            data.get('tz'), now_iso(),
        )
    )
    db.commit()
    return jsonify({"stored": True, "updated": existing is not None}), 200

@bp.route('/device/data', methods=['DELETE'])
@token_required
def delete_device_data():
    db = get_db()
    db.execute("DELETE FROM daily_summaries WHERE device_id = ?", (g.device['id'],))
    db.commit()
    return '', 204
