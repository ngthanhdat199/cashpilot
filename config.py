import os
import logging
import json


# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load configuration
try:
    config_path = os.path.join(BASE_DIR, "config.json")
    with open(config_path, "r") as config_file:
        config = json.load(config_file)
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=getattr(logging, config["settings"]["logging_level"]))
    logger.info(f"Configuration loaded successfully from {config_path}")
except Exception as e:
    print(f"⚠️  Failed to load config.json: {e}")
    exit(1)

