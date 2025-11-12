import os
from src.track_py.config import PROJECT_ROOT

VERSION = "VERSION"
BUILD_TIME = "BUILD_TIME"


def get_version() -> str:
    try:
        version_file = os.path.join(PROJECT_ROOT, VERSION)
        with open(version_file) as f:
            return f.read().strip()
    except Exception:
        return "unknown"


# Get build time
def get_build_time() -> str:
    try:
        build_time_file = os.path.join(PROJECT_ROOT, BUILD_TIME)
        with open(build_time_file) as f:
            return f.read().strip()
    except Exception:
        return "unknown"
