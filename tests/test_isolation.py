"""The test suite must never write into the repository's real instance/ folder."""
import os
from app import create_app

REPO_INSTANCE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance')
REAL_LOG = os.path.join(REPO_INSTANCE, 'server.log')

def log_state():
    """(size, modified time) of the real request log, or None when it does not exist."""
    try:
        st = os.stat(REAL_LOG)
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns)

def test_test_apps_leave_the_real_request_log_unchanged(app, client, isolated_instance):
    before = log_state()

    # The shared fixture's app logs into the temporary instance folder
    assert os.path.abspath(app.instance_path) != os.path.abspath(REPO_INSTANCE)
    assert os.path.dirname(os.path.abspath(app.config['LOG_FILE'])) == os.path.abspath(isolated_instance)
    assert client.get('/api/health').status_code == 200

    # So does an app built with no test config at all (default database, secret key and log)
    bare = create_app()
    assert os.path.abspath(bare.instance_path) == os.path.abspath(isolated_instance)
    assert bare.test_client().get('/api/health').status_code == 200

    with open(os.path.join(isolated_instance, 'server.log'), encoding='utf-8') as f:
        assert 'GET /api/health 200' in f.read()
    assert log_state() == before
