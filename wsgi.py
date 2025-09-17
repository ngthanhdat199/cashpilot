import sys
from const import PROJECT_HOME
from main import app

# Add your project directory to the Python path
if PROJECT_HOME not in sys.path:
    sys.path = [PROJECT_HOME] + sys.path

# For PythonAnywhere, the WSGI application should be called 'application'
application = app

if __name__ == "__main__":
    application.run()
