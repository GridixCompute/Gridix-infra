"""Slow deterministic workload for the node-death demo: work ~30s, then write sha256(input).

Long enough that the agent can be killed mid-run (to simulate a dead node), short enough
that the reassigned attempt finishes the demo. Same GRIDIX_INPUT/GRIDIX_OUTPUT contract.
"""

import hashlib
import os
import pathlib
import time

time.sleep(30)

inp = pathlib.Path(os.environ.get("GRIDIX_INPUT", "/gridix/input"))
out = pathlib.Path(os.environ.get("GRIDIX_OUTPUT", "/gridix/output/result"))
data = inp.read_bytes() if inp.exists() else b""
out.write_bytes(hashlib.sha256(data).hexdigest().encode())
