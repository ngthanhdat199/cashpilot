# map to PythonAnywhere WSGI configuration file:
# https://www.pythonanywhere.com/user/thanhdat19/files/var/www/thanhdat19_pythonanywhere_com_wsgi.py
import sys

# Add your project directory to the Python path
project_home = '/home/thanhdat19/track-money'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Import your Flask app and bot components
from src.track_py.main import app

# For PythonAnywhere, the WSGI application should be called 'application'
application = app

if __name__ == "__main__":
    application.run()
