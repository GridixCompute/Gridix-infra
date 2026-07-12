"""Medium workload (~4s) for load/chaos tests: long enough to be in-flight when chaos hits,
short enough to measure throughput over many jobs. Writes sha256(input) to output."""

import hashlib
import os
import pathlib
import time

time.sleep(4)

inp = pathlib.Path(os.environ.get("GRIDIX_INPUT", "/gridix/input"))
out = pathlib.Path(os.environ.get("GRIDIX_OUTPUT", "/gridix/output/result"))
data = inp.read_bytes() if inp.exists() else b""
out.write_bytes(hashlib.sha256(data).hexdigest().encode())
