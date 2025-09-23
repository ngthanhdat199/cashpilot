import os
import json

# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
config = {}  # global in memory

# Load configuration immediately when module is imported
try:
    with open(CONFIG_PATH, "r") as config_file:
        config = json.load(config_file)
    print(f"✅ Configuration loaded successfully from {CONFIG_PATH}")
except Exception as e:
    print(f"⚠️  Failed to load config.json: {e}")
    exit(1)

def load_config():
    """Reload configuration from config.json"""
    global config
    try:
        with open(CONFIG_PATH, "r") as config_file:
            config = json.load(config_file)
        print(f"✅ Configuration reloaded successfully from {CONFIG_PATH}")
        return config
    except Exception as e:
        print(f"⚠️  Failed to reload config.json: {e}")
        return None
    
def save_config():
    """Save updated configuration to config.json"""
    global config
    try:
        with open(CONFIG_PATH, "w") as config_file:
            json.dump(config, config_file, indent=4)
        return True
    except Exception as e:
        print(f"⚠️  Failed to save config.json: {e}")
        return False