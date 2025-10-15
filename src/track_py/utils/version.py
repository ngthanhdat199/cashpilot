import os
from src.track_py.config import BASE_DIR

def get_version():
    try:
        version_file = os.path.join(BASE_DIR, "VERSION")
        with open(version_file) as f:
            return f.read().strip()
    except Exception:
        return "unknown"