"""Put the image-server package on sys.path so `pytest image_server/tests` can import it.

The repo suite is unaffected: pyproject sets testpaths=["tests"], so this conftest and the
image-server tests are collected only when image_server/ is passed to pytest explicitly.
Mirrors node/conftest.py.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
