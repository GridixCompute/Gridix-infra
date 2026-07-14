"""Reference GPU throughput benchmark for GRIDIX providers.

Runs a large single-precision GEMM (matrix multiply) on the GPU and reports sustained TFLOPs on
a line the agent's harness parses: ``GRIDIX_TFLOPS=<float>``. FP32 is used because the
coordinator's reference table (`app.benchmark.GPU_REFERENCE_TFLOPS`) is FP32 (A100 ~19.5, etc.).

Providers may substitute their own harness image — any container that runs under ``--gpus all``
and prints ``GRIDIX_TFLOPS=<float>`` works. This is just a sane, verifiable default.
"""

import os
import time

import cupy as cp

N = int(os.environ.get("GRIDIX_GEMM_N", "8192"))  # square matrix dimension
ITERS = int(os.environ.get("GRIDIX_GEMM_ITERS", "10"))


def main() -> None:
    a = cp.random.rand(N, N, dtype=cp.float32)
    b = cp.random.rand(N, N, dtype=cp.float32)
    # Warm up (kernel autotune, allocation) before timing.
    cp.matmul(a, b)
    cp.cuda.Device().synchronize()

    start = time.perf_counter()
    for _ in range(ITERS):
        c = cp.matmul(a, b)  # noqa: F841 - result kept alive so the op isn't elided
    cp.cuda.Device().synchronize()
    seconds_per_iter = (time.perf_counter() - start) / ITERS

    flops = 2.0 * N**3  # multiply-add per output element
    tflops = flops / seconds_per_iter / 1e12
    print(f"GRIDIX_TFLOPS={tflops:.2f}")


if __name__ == "__main__":
    main()
