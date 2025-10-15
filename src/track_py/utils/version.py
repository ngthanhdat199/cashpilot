import os
from src.track_py.config import PROJECT_ROOT

def get_version():
    try:
        version_file = os.path.join(PROJECT_ROOT, "VERSION")
        with open(version_file) as f:
            return f.read().strip()
    except Exception:
        return "unknown"