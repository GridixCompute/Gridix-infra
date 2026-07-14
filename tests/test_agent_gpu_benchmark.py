"""Agent GPU benchmark harness (Session 11.7) — measured hardware, not self-declared.

Hermetic: nvidia-smi / docker are mocked via `gpu_benchmark._run`, so no GPU or Docker is
needed. Proves the harness measures identity/VRAM/throughput/fingerprint, that its signature
interoperates with the coordinator's verifier, and that the strengthened validation rejects a
declaration that contradicts the measured card.
"""

import gpu_benchmark
from app.benchmark import sign_report, validate_benchmark, verify_signature

# nvidia-smi CSV: name, memory.total (MiB), uuid
_A100 = "NVIDIA A100-SXM4-40GB, 40960, GPU-aaaa1111-bbbb-2222-cccc-333344445555"
_T4 = "Tesla T4, 15360, GPU-tttt9999-8888-7777-6666-555544443333"


def _fake_run(nvidia_out=None, docker_out=None):
    def run(argv, timeout):
        if argv[0] == "nvidia-smi":
            return nvidia_out
        if argv[0] == "docker":
            return docker_out
        return None

    return run


def test_probe_parses_multiple_gpus(monkeypatch):
    monkeypatch.setattr(gpu_benchmark, "_run", _fake_run(nvidia_out=f"{_A100}\n{_A100}\n"))
    gpus = gpu_benchmark.probe_nvidia_smi()
    assert len(gpus) == 2
    assert gpus[0]["name"].startswith("NVIDIA A100")
    assert gpus[0]["vram_mb"] == 40960
    assert gpus[0]["uuid"].startswith("GPU-aaaa1111")


def test_probe_empty_without_driver(monkeypatch):
    monkeypatch.setattr(gpu_benchmark, "_run", _fake_run(nvidia_out=None))  # nvidia-smi missing
    assert gpu_benchmark.probe_nvidia_smi() == []


def test_normalize_model():
    assert gpu_benchmark.normalize_gpu_model("NVIDIA A100-SXM4-40GB") == "A100"
    assert gpu_benchmark.normalize_gpu_model("Tesla T4") == "T4"
    assert gpu_benchmark.normalize_gpu_model("NVIDIA H100 80GB HBM3") == "H100"
    assert gpu_benchmark.normalize_gpu_model("Some Random Card") is None


def test_fingerprint_is_stable_and_collides_for_same_card():
    a = gpu_benchmark.hardware_fingerprint([{"uuid": "GPU-x"}, {"uuid": "GPU-y"}])
    b = gpu_benchmark.hardware_fingerprint([{"uuid": "GPU-y"}, {"uuid": "GPU-x"}])  # order-agnostic
    assert a == b  # same physical set -> same fingerprint (clone-as-many-nodes collides)
    assert gpu_benchmark.hardware_fingerprint([{"uuid": "GPU-z"}]) != a
    assert gpu_benchmark.hardware_fingerprint([]) is None


def test_collect_metrics_measures_a100_box(monkeypatch):
    monkeypatch.setattr(
        gpu_benchmark, "_run", _fake_run(nvidia_out=f"{_A100}\n", docker_out="GRIDIX_TFLOPS=18.9\n")
    )
    m = gpu_benchmark.collect_metrics(cpu_cores=8, memory_mb=32768, bench_image="grx/bench:1")
    assert m["gpu_model"] == "A100"
    assert m["gpu_vram_mb"] == 40960
    assert m["gpu_tflops"] == 18.9
    assert m["gpu_count"] == 1
    assert m["hardware_fingerprint"]  # present


def test_collect_metrics_cpu_only_box(monkeypatch):
    monkeypatch.setattr(gpu_benchmark, "_run", _fake_run(nvidia_out=None))
    m = gpu_benchmark.collect_metrics(cpu_cores=4, memory_mb=8192)
    assert m["gpu_model"] is None
    assert m["gpu_vram_mb"] == 0
    assert m["gpu_tflops"] == 0.0
    assert "hardware_fingerprint" not in m


def test_no_bench_image_reports_zero_tflops(monkeypatch):
    monkeypatch.setattr(gpu_benchmark, "_run", _fake_run(nvidia_out=f"{_A100}\n"))
    m = gpu_benchmark.collect_metrics(cpu_cores=8, memory_mb=32768, bench_image=None)
    assert m["gpu_tflops"] == 0.0  # measured throughput absent, not faked


# ── interop with the coordinator ────────────────────────────────────────────────────────────
def test_agent_signature_verifies_on_coordinator():
    metrics = {"gpu_model": "A100", "gpu_vram_mb": 40960, "gpu_tflops": 18.9}
    key = "provider-secret-key"
    sig = gpu_benchmark.sign_metrics(metrics, key)
    assert sig == sign_report(metrics, key)  # byte-identical canonical encoding
    assert verify_signature(metrics, sig, key)  # coordinator accepts it


def test_validation_accepts_matching_measured_hardware(monkeypatch):
    monkeypatch.setattr(
        gpu_benchmark, "_run", _fake_run(nvidia_out=f"{_A100}\n", docker_out="GRIDIX_TFLOPS=18.9\n")
    )
    m = gpu_benchmark.collect_metrics(cpu_cores=8, memory_mb=32768, bench_image="grx/bench:1")
    ok, reason = validate_benchmark(m, declared_gpu_model="A100")
    assert ok, reason


def test_validation_rejects_declared_a100_measured_t4(monkeypatch):
    """A box declaring an A100 but whose nvidia-smi shows a T4 is rejected on identity alone."""
    monkeypatch.setattr(
        gpu_benchmark, "_run", _fake_run(nvidia_out=f"{_T4}\n", docker_out="GRIDIX_TFLOPS=8.0\n")
    )
    m = gpu_benchmark.collect_metrics(cpu_cores=8, memory_mb=16384, bench_image="grx/bench:1")
    ok, reason = validate_benchmark(m, declared_gpu_model="A100")
    assert not ok
    assert "measured hardware is T4" in reason


def test_validation_rejects_declared_gpu_no_hardware():
    """Declares an A100 but the box has no GPU (measured None, 0 TFLOPs) -> rejected."""
    m = {"gpu_model": None, "gpu_vram_mb": 0, "gpu_tflops": 0.0}
    ok, reason = validate_benchmark(m, declared_gpu_model="A100")
    assert not ok
    assert "no GPU throughput" in reason
