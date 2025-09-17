import os
import json


# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load configuration
try:
    config_path = os.path.join(BASE_DIR, "config.json")
    with open(config_path, "r") as config_file:
        config = json.load(config_file)

except Exception as e:
    print(f"⚠️  Failed to load config.json: {e}")
    exit(1)

