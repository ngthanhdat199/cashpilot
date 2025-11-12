run:
	.venv/bin/python wsgi.py

cli:
	.venv/bin/python -m src.track_py.cli.__init__

test:
	.venv/bin/python -m unittest discover -s tests