import datetime
import logging
import logging.handlers
import os
import re
import time
from flask import g, request
from .clientip import client_ip

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
UNSAFE = re.compile(r'[^\x21-\x7e]')

# One logger per log file, so creating several apps (tests) never opens a file twice
_loggers = {}

def get_logger(path):
    path = os.path.abspath(path)
    if path not in _loggers:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        logger = logging.getLogger(f'shadow.requests.{len(_loggers)}')
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8', delay=True)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        _loggers[path] = logger
    return _loggers[path]

def register(app):
    """One line per request: time, method, path (no query string), status, duration, client IP.

    Never bodies, headers, passwords or tokens.
    """
    logger = get_logger(app.config['LOG_FILE'])

    @app.before_request
    def start_timer():
        g.request_started = time.perf_counter()

    @app.after_request
    def log_request(response):
        started = g.get('request_started')
        duration_ms = round((time.perf_counter() - started) * 1000) if started else 0
        # Spaces and control characters are replaced so a crafted path cannot forge a line
        path = UNSAFE.sub('?', request.path)[:200]
        logger.info('%s %s %s %d %dms %s',
                    datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    request.method, path, response.status_code, duration_ms, client_ip())
        return response
