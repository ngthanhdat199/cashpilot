import json
from pathlib import Path

# Get the directory where this script is located
BASE_DIR = Path(__file__).resolve().parent  # /src/track_py
PROJECT_ROOT = BASE_DIR.parents[1]  # /track_py
CONFIG_PATH = PROJECT_ROOT / "config.json"
config = {}  # global in memory

# Load configuration immediately when module is imported
try:
    with open(CONFIG_PATH, "r") as config_file:
        config = json.load(config_file)
    print(f"✅ Configuration loaded successfully from {CONFIG_PATH}")
except Exception as e:
    print(f"⚠️  Failed to load config.json: {e}")
    exit(1)


def save_config() -> None:
    """Save updated configuration to config.json"""
    global config
    try:
        with open(CONFIG_PATH, "w") as config_file:
            json.dump(config, config_file, indent=4)
        return
    except Exception as e:
        print(f"⚠️  Failed to save config.json: {e}")
        return
