import src.track_py.utils.asset as asset
from src.track_py.utils.logger import logger


if __name__ == "__main__":
    logger.info("Starting assets data migration...")
    asset.migrate_assets_data()
    logger.info("Assets data migration completed.")
