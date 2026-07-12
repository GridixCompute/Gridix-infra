"""Timeout probe: sleep far past any sane job budget.

Submit with a short ``timeout_seconds`` (e.g. 5). The agent must kill AND remove the
container at the wall-clock deadline and mark the job failed/timeout — never let it hang
forever. After the run, ``docker ps -a`` should show no leftover ``gridix-*`` container.
"""

import time

print("sleeping 600s — expect to be killed at the job timeout", flush=True)
time.sleep(600)
print("this line should never print")
