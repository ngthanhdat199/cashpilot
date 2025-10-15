import sys
import os

# Absolute path to src folder
PROJECT_HOME = '/home/thanhdat19/track-money/src'

# Add src folder to sys.path
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

# Import app from the package inside src (no 'src.' prefix)
from track_py.main import app

# Required for PythonAnywhere
application = app


# For local testing purposes
# if __name__ == "__main__":
#     application.run()
