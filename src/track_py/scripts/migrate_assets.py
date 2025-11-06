import src.track_py.utils.sheet as sheet
from src.track_py.utils.logger import logger


if __name__ == "__main__":
    logger.info("Starting assets data migration...")
    sheet.migrate_assets_data()
    logger.info("Assets data migration completed.")
