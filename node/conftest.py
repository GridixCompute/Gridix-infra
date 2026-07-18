"""Put the node package on sys.path so `pytest node/tests` can import gridix_node.

The repo suite is unaffected: pyproject sets testpaths=["tests"], so this conftest and the
node tests are collected only when node/ is passed to pytest explicitly.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
