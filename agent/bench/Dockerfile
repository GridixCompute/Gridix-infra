# Reference GRIDIX GPU benchmark image.
# Build:  docker build -t gridix/bench:1 agent/bench
# Run  :  docker run --rm --gpus all gridix/bench:1   # prints GRIDIX_TFLOPS=<float>
# Point the agent at it with GRIDIX_BENCH_IMAGE=gridix/bench:1.
FROM nvidia/cuda:12.3.1-runtime-ubuntu22.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# cupy gives a real cuBLAS GEMM without pulling the full deep-learning stack.
RUN pip3 install --no-cache-dir cupy-cuda12x

COPY bench_gemm.py /bench_gemm.py
ENTRYPOINT ["python3", "/bench_gemm.py"]
