import os
from flask import abort, send_from_directory
from werkzeug.security import safe_join

def register(app):
    # Serves the built dashboard only when SHADOW_DASHBOARD_DIR points at an existing folder
    folder = app.config.get('DASHBOARD_DIR')
    if not folder or not os.path.isdir(folder):
        return
    folder = os.path.abspath(folder)

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def dashboard(path):
        # Unknown /api paths stay 404 instead of falling back to the app
        if path == 'api' or path.startswith('api/'):
            abort(404)
        if path:
            full = safe_join(folder, path)
            # Paths that try to leave the folder (..) are refused
            if full is None:
                abort(404)
            if os.path.isfile(full):
                return send_from_directory(folder, path)
        # Single-page app fallback
        return send_from_directory(folder, 'index.html')
