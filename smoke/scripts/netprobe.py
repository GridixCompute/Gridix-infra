"""Egress-isolation probe: try to reach the internet, record the verdict.

Submitted as a NORMAL job (allow_egress=false) it must run with ``--network none``. It
connects straight to an IP (no DNS, which is itself blocked) so a success genuinely means
the container escaped isolation. Writes BLOCKED (good — isolated) or REACHED (bad —
isolation broken) to the output so the developer can download and read the result.
"""

import os
import pathlib
import socket

out_path = pathlib.Path(os.environ.get("GRIDIX_OUTPUT", "/gridix/output/result"))

verdict = b"BLOCKED"
try:
    # 1.1.1.1:443 by IP — no name resolution needed.
    with socket.create_connection(("1.1.1.1", 443), timeout=3):
        verdict = b"REACHED"
except OSError:
    verdict = b"BLOCKED"

out_path.write_bytes(verdict)
print(verdict.decode())
