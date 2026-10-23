import os
import secrets
from flask import Flask, jsonify, request, g

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    # Default configuration
    db_default = os.path.join(app.instance_path, 'shadow.db')
    app.config.from_mapping(
        DATABASE=os.environ.get('SHADOW_DB', db_default),
        SECRET_KEY=os.environ.get('SHADOW_SECRET_KEY'),
        COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
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

    # Lockout state: (ip, username) -> [timestamp, count]
    # In-memory dict is fine as per requirements
    app.lockout_data = {}

    @app.before_request
    def check_security():
        # Health check is public
        if request.path == '/api/health':
            return

        # POST/PUT/DELETE require X-Requested-With and JSON body
        if request.method in ['POST', 'PUT', 'DELETE']:
            if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
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
    from . import auth, teams
    app.register_blueprint(auth.bp)
    app.register_blueprint(teams.bp)

    return app
