import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app as flask_app


def app(environ, start_response):
    path = environ.get("PATH_INFO", "") or "/"
    for prefix in ("/api/index.py", "/api/index"):
        if path == prefix:
            path = "/"
            break
        if path.startswith(prefix + "/"):
            path = path[len(prefix):]
            break
    environ["PATH_INFO"] = path or "/"
    return flask_app(environ, start_response)
          
