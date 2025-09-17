import os
import logging
from config import config

logger = logging.getLogger(__name__)
logging.basicConfig(level=getattr(logging, config["settings"]["logging_level"]))
# logger.info(f"Configuration loaded successfully from {config_path}")