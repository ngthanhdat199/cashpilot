import sys
from src.track_py.const import PROJECT_HOME
from src.track_py.main import app

# Add your project directory to the Python path
# if PROJECT_HOME not in sys.path:
#     sys.path = [PROJECT_HOME] + sys.path

# # For PythonAnywhere, the WSGI application should be called 'application'
# application = app

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
