import os
import sys
from urllib.parse import urlsplit

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app as flask_app


def _extract_real_path(environ):
    path = environ.get("PATH_INFO") or "/"
    for key in ("HTTP_X_ORIGINAL_URL", "HTTP_X_REWRITE_URL", "REQUEST_URI"):
        raw = environ.get(key)
        if raw and path in ("/api/index", "/api/index.py", "/"):
            parsed_path = urlsplit(raw).path
            if parsed_path and parsed_path not in ("/api/index", "/api/index.py"):
                path = parsed_path
                break

    for prefix in ("/api/index.py", "/api/index"):
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix):] or "/"
    return path or "/"


def app(environ, start_response):
    raw_path = environ.get("PATH_INFO")
    clean_path = _extract_real_path(environ)
    environ["PATH_INFO"] = clean_path
    print(f"WSGI {environ.get('REQUEST_METHOD')} raw={raw_path} -> clean={clean_path}")
    return flask_app(environ, start_response)
    
