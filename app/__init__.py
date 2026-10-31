import os
import secrets
from flask import Flask, jsonify, request, g

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

    # Database setup
    from . import db
    db.init_db(app)
    app.teardown_appcontext(db.close_db)

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

    @app.before_request
    def check_security():
        # Health check is public
        if request.path == '/api/health':
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
        return response

    @app.route('/api/health')
    def health():
        return jsonify({"ok": True})

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
