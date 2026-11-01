import os
import secrets
import sqlite3
from flask import Flask, jsonify, request, g

VERSION = "1"
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, static_folder=None)
    from . import retention
    retention_days, audit_retention_days = retention.retention_settings()

    # Default configuration
    db_default = os.path.join(app.instance_path, 'shadow.db')
    app.config.from_mapping(
        DATABASE=os.environ.get('SHADOW_DB', db_default),
        SECRET_KEY=os.environ.get('SHADOW_SECRET_KEY'),
        COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
        DASHBOARD_DIR=os.environ.get('SHADOW_DASHBOARD_DIR'),
        RETENTION_DAYS=retention_days,
        AUDIT_RETENTION_DAYS=audit_retention_days,
        # Empty = ignore proxy headers; see app/clientip.py
        CLIENT_IP_HEADER=os.environ.get('SHADOW_CLIENT_IP_HEADER', '').strip(),
        # Empty = registration stays open (development)
        ENROLL_CODE=os.environ.get('SHADOW_ENROLL_CODE') or None,
        LOG_FILE=os.path.join(app.instance_path, 'server.log'),
    )

    if test_config:
        app.config.from_mapping(test_config)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Persist secret key if not provided
    if not app.config['SECRET_KEY']:
        key_path = os.path.join(app.instance_path, 'secret_key')
        if os.path.exists(key_path):
            with open(key_path, 'rb') as f:
                app.config['SECRET_KEY'] = f.read().decode('utf-8')
        else:
            app.config['SECRET_KEY'] = secrets.token_hex(32)
            with open(key_path, 'w') as f:
                f.write(app.config['SECRET_KEY'])

    # Session cookie config
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=app.config['COOKIE_SECURE'],
    )

    # Request log (instance/server.log); registered first so it times every request
    from . import requestlog
    requestlog.register(app)

    # Database setup
    from . import db
    db.init_db(app)
    app.teardown_appcontext(db.close_db)

    # Decisions saved before their signal was stored get one from current data (only NULLs)
    from . import data
    with app.app_context():
        data.backfill_decision_signals()

    # Old summaries and audit rows are purged on startup, then at most every 6 hours
    with app.app_context():
        retention.run_purge(app, db.get_db())

    @app.before_request
    def purge_old_data():
        if retention.purge_due(app):
            retention.run_purge(app, db.get_db())

    # Lockout state: (ip, username) -> [timestamp, count]
    # In-memory dict is fine as per requirements
    app.lockout_data = {}
    # Device rate limit state: device_id -> [timestamps]
    app.device_rate_data = {}
    # Invite preview rate limit state: account_id -> [timestamps]
    app.preview_rate_data = {}
    # Registration rate limit state: client ip -> [timestamps]
    app.register_rate_data = {}

    @app.before_request
    def check_security():
        # Health check and public config are public
        if request.path in ('/api/health', '/api/config'):
            return

        # POST/PUT/DELETE require X-Requested-With and JSON body
        if request.method in ['POST', 'PUT', 'DELETE']:
            # Device token routes never use cookies, so they are exempt from this check
            if (request.endpoint not in devices.TOKEN_ENDPOINTS
                    and request.headers.get('X-Requested-With') != 'XMLHttpRequest'):
                return jsonify({"error": "Missing X-Requested-With header"}), 400
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

    @app.after_request
    def add_security_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
        response.headers['Content-Security-Policy'] = CSP
        # Only behind HTTPS (the tunnel); a plain-http dev server must not pin HTTPS
        if app.config['COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=15552000'
        return response

    @app.route('/api/health')
    def health():
        try:
            db_ok = db.get_db().execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            db_ok = False
        return jsonify({"ok": True, "version": VERSION, "db": db_ok})

    @app.route('/api/config')
    def public_config():
        return jsonify({"enroll_required": bool(app.config['ENROLL_CODE'])})

    # Register blueprints
    from . import auth, teams, sharing, devices, me_views, manager
    app.register_blueprint(auth.bp)
    app.register_blueprint(teams.bp)
    app.register_blueprint(sharing.bp)
    app.register_blueprint(devices.bp)
    app.register_blueprint(me_views.bp)
    app.register_blueprint(manager.bp)

    from . import dashboard
    dashboard.register(app)

    return app
