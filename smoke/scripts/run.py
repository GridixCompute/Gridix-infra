"""Happy-path smoke workload: read input, write sha256(input) to output.

Deterministic on purpose — the output is a pure function of the input, so the same job
can double as a canary (the coordinator already knows sha256 of the input it sent) and as
a redundant-execution vote (honest providers agree byte-for-byte). Reads/writes only via
the GRIDIX_INPUT / GRIDIX_OUTPUT contract the agent injects (build_run_argv).
"""

import hashlib
import os
import pathlib
import sys

in_path = pathlib.Path(os.environ.get("GRIDIX_INPUT", "/gridix/input"))
out_path = pathlib.Path(os.environ.get("GRIDIX_OUTPUT", "/gridix/output/result"))

data = in_path.read_bytes() if in_path.exists() else b""
digest = hashlib.sha256(data).hexdigest().encode()

try:
    out_path.write_bytes(digest)
except PermissionError as exc:
    # This is the classic non-root output-mount bug (runbook P0.4): the container runs as
    # uid 65534 but the bind-mounted output dir isn't writable by it. Fail loud, not silent.
    print(f"cannot write output (non-root mount permission?): {exc}", file=sys.stderr)
    sys.exit(3)

print(f"wrote {len(digest)} bytes: {digest.decode()}")
