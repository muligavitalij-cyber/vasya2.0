import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app as flask_app


def app(environ, start_response):
  path = environ.get("PATH_INFO", "")
  if path in ("/api/index.py", "/api/index"):
    environ["PATH_INFO"] = "/"
  elif path.startswith("/api/index.py/"):
    environ["PATH_INFO"] = path[len("/api/index.py") :]
  return flask_app(environ, start_response)
  

