"""Local laptop benchmark for FormulaLM GGUF models (Windows 11, CPU-only, 8 GB RAM).

Features:
- Checks installed local runtimes (Ollama and llama.cpp: ``llama-server`` / ``llama-cli``).
- Inspects live OS, CPU, total RAM, available RAM, and free disk space.
- Prints a concrete "what to close before running" checklist for 8 GB laptops.
- Memory-safety gate: estimates working-set RAM (``size_mb * 1.25 + 350 MB``) and SKIPS
  any quantization that does not fit in currently available RAM instead of forcing OOM/swap.
- For each fitting quantization (default order: ``Q4_K_M``, ``Q5_K_M``, ``Q8_0``), records:
  file size (MB), cold load time (s), peak process RSS (MB), tokens/second, and executable
  accuracy (+ 95% Wilson CI) on the 130-example subset (``test_real_v2`` 50 + ``test_real`` 80).
- Writes ``results/local_benchmark/local_benchmark.json`` and ``local_benchmark.md``.

Usage:
    # 1. Pre-flight check only (verifies RAM, disk, Ollama/llama.cpp install, fit estimates):
    uv run python scripts/benchmark_local.py --dry-run

    # 2. Run benchmark against GGUFs downloaded into ./models/gguf_v2/:
    uv run python scripts/benchmark_local.py --models-dir models/gguf_v2 --engine auto
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from src.eval.compare_v1_v2 import wilson_ci  # noqa: E402
from src.eval.run_eval import (  # noqa: E402
    LlamaCppBackend,
    OllamaBackend,
    evaluate,
)

DEFAULT_QUANTS: tuple[tuple[str, str, str], ...] = (
    ("q4_k_m", "Q4_K_M", "formulalm-qwen3-1.7b-v2-q4_k_m.gguf"),
    ("q5_k_m", "Q5_K_M", "formulalm-qwen3-1.7b-v2-q5_k_m.gguf"),
    ("q8_0", "Q8_0", "formulalm-qwen3-1.7b-v2-q8_0.gguf"),
)

# Conservative RAM safety buffer for 8 GB Windows 11 laptops (KV cache + runtime + OS headroom).
RAM_MULTIPLIER = 1.25
RAM_OVERHEAD_MB = 350.0
OS_HEADROOM_MB = 350.0

CLOSE_BEFORE_RUNNING_CHECKLIST: tuple[str, ...] = (
    "Close web browsers (Chrome / Edge / Firefox — tabs easily consume 2–4 GB RAM).",
    "Close heavy Electron apps (Microsoft Teams, Discord, Slack, Spotify).",
    "Close extra IDE windows or language servers you don't need while running.",
    "Pause OneDrive syncing temporarily so disk I/O does not stall model loading.",
    "Close Docker Desktop / WSL2 if running (`wsl --shutdown` frees 1–3 GB RAM).",
    "Aim for at least 2.2 GB free RAM for Q4_K_M, 2.5 GB for Q5_K_M, and 3.0 GB for Q8_0.",
)


# ---------------------------------------------------------------------------
# Cross-platform memory, hardware & runtime inspection (zero extra packages)
# ---------------------------------------------------------------------------


def get_memory_mb() -> dict[str, float]:
    """Return ``total_mb`` and ``available_mb`` system RAM."""
    if sys.platform == "win32":

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return {
            "total_mb": round(stat.ullTotalPhys / (1024 * 1024), 1),
            "available_mb": round(stat.ullAvailPhys / (1024 * 1024), 1),
        }

    # Linux / macOS fallback
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        vals: dict[str, float] = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("MemTotal:", "MemAvailable:"):
                vals[parts[0]] = float(parts[1]) / 1024.0
        return {
            "total_mb": round(vals.get("MemTotal:", 0.0), 1),
            "available_mb": round(vals.get("MemAvailable:", 0.0), 1),
        }
    return {"total_mb": 0.0, "available_mb": 0.0}


def get_process_rss_mb(pid: int) -> float | None:
    """Return resident working-set memory (MB) for ``pid``, or ``None`` if unavailable."""
    if sys.platform == "win32":
        try:

            class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            PROCESS_VM_READ = 0x0010
            hproc = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid
            )
            if not hproc:
                return None
            try:
                pmc = _PROCESS_MEMORY_COUNTERS()
                pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
                ok = ctypes.windll.psapi.GetProcessMemoryInfo(hproc, ctypes.byref(pmc), pmc.cb)
                if ok:
                    return round(pmc.PeakWorkingSetSize / (1024 * 1024), 1)
            finally:
                ctypes.windll.kernel32.CloseHandle(hproc)
        except Exception:
            return None
    status_p = Path(f"/proc/{pid}/status")
    if status_p.is_file():
        for line in status_p.read_text(encoding="utf-8").splitlines():
            if line.startswith(("VmHWM:", "VmRSS:")):
                parts = line.split()
                if len(parts) >= 2:
                    return round(float(parts[1]) / 1024.0, 1)
    return None


def estimate_required_ram_mb(file_size_mb: float) -> float:
    """Conservative estimate of RAM needed to load and run a GGUF file on CPU without swapping."""
    return round(file_size_mb * RAM_MULTIPLIER + RAM_OVERHEAD_MB, 1)


def check_memory_fit(
    file_size_mb: float,
    available_ram_mb: float,
    *,
    headroom_mb: float = OS_HEADROOM_MB,
) -> dict[str, Any]:
    """Decide whether a GGUF file fits safely in currently available RAM."""
    required_mb = estimate_required_ram_mb(file_size_mb)
    budget_mb = max(0.0, round(available_ram_mb - headroom_mb, 1))
    fits = required_mb <= budget_mb
    reason = (
        f"fits (est. {required_mb:.0f} MB <= safe budget {budget_mb:.0f} MB)"
        if fits
        else (
            f"does NOT fit safely: est. {required_mb:.0f} MB needed > "
            f"{budget_mb:.0f} MB safe budget ({available_ram_mb:.0f} MB free - "
            f"{headroom_mb:.0f} MB OS headroom)"
        )
    )
    return {
        "fits": fits,
        "file_size_mb": round(file_size_mb, 2),
        "estimated_required_mb": required_mb,
        "available_ram_mb": round(available_ram_mb, 1),
        "safe_budget_mb": budget_mb,
        "reason": reason,
    }


def _probe_binary(name: str, args: list[str]) -> dict[str, Any]:
    exe = shutil.which(name)
    if not exe:
        return {"installed": False, "path": None, "version": None}
    try:
        out = subprocess.check_output(
            [exe, *args], text=True, stderr=subprocess.STDOUT, timeout=10
        ).strip()
        first_line = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
    except Exception as exc:
        first_line = f"error probing version: {exc}"
    return {"installed": True, "path": exe, "version": first_line}


def check_local_environment(work_dir: Path | None = None) -> dict[str, Any]:
    """Inspect OS, CPU, RAM, free disk, and installed Ollama / llama.cpp runtimes."""
    mem = get_memory_mb()
    disk = shutil.disk_usage(work_dir or REPO_ROOT)
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_threads": os.cpu_count(),
        "ram_total_mb": mem["total_mb"],
        "ram_available_mb": mem["available_mb"],
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "runtimes": {
            "ollama": _probe_binary("ollama", ["--version"]),
            "llama_server": _probe_binary("llama-server", ["--version"]),
            "llama_cli": _probe_binary("llama-cli", ["--version"]),
        },
    }


def install_instructions_text() -> str:
    return (
        "Neither `llama-server` (llama.cpp) nor `ollama` was found on PATH.\n"
        "Install one of them (free, no GPU required on Windows 11):\n"
        "  Option A — llama.cpp (recommended, lowest RAM overhead):\n"
        "    winget install ggml.llamacpp\n"
        "    (or download llama-*-bin-win-cpu-x64.zip from https://github.com/ggml-org/llama.cpp/releases)\n"
        "  Option B — Ollama:\n"
        "    winget install Ollama.Ollama\n"
        "    (or download from https://ollama.com/download/windows)\n"
    )


# ---------------------------------------------------------------------------
# Benchmarking runners (llama-server & Ollama)
# ---------------------------------------------------------------------------


@dataclass
class _PeakSampler:
    pid: int
    interval_s: float = 0.25
    peak_rss_mb: float = 0.0
    _stop: threading.Event | None = None
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop = threading.Event()

        def _loop() -> None:
            assert self._stop is not None
            while not self._stop.is_set():
                rss = get_process_rss_mb(self.pid)
                if rss is not None and rss > self.peak_rss_mb:
                    self.peak_rss_mb = rss
                self._stop.wait(self.interval_s)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        rss = get_process_rss_mb(self.pid)
        if rss is not None and rss > self.peak_rss_mb:
            self.peak_rss_mb = rss
        return round(self.peak_rss_mb, 1)


class _TimingWrapperBackend:
    """Wraps LlamaCppBackend or OllamaBackend to record per-call token throughput."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = inner.name
        self.gen_tps: list[float] = []
        self.prompt_tps: list[float] = []

    def provenance(self) -> dict[str, Any]:
        fn = getattr(self.inner, "provenance", None)
        return fn() if callable(fn) else {}

    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        out = self.inner.generate(messages, **kwargs)
        timings = getattr(self.inner, "last_timings", None) or {}
        if timings.get("predicted_per_second"):
            self.gen_tps.append(float(timings["predicted_per_second"]))
        if timings.get("prompt_per_second"):
            self.prompt_tps.append(float(timings["prompt_per_second"]))
        return out


def _benchmark_with_llamacpp(
    gguf_path: Path,
    *,
    qkey: str,
    qtype: str,
    out_root: Path,
    port: int,
    threads: int,
    limit: int | None,
    formula_timeout: float,
) -> dict[str, Any]:
    server_exe = shutil.which("llama-server")
    assert server_exe is not None
    mem_before = get_memory_mb()["available_mb"]
    t_start = time.perf_counter()
    proc = subprocess.Popen(
        [
            server_exe,
            "-m",
            str(gguf_path),
            "-ngl",
            "0",
            "-c",
            "2048",
            "-t",
            str(threads),
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    sampler = _PeakSampler(pid=proc.pid)
    sampler.start()
    try:
        ready = False
        for _ in range(180):
            if proc.poll() is not None:
                err_txt = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"llama-server crashed during load: {err_txt[:400]}")
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ready:
            raise TimeoutError(f"llama-server timed out loading {gguf_path.name}")
        load_time_s = round(time.perf_counter() - t_start, 2)

        inner = LlamaCppBackend(
            base_url=f"http://127.0.0.1:{port}",
            model=gguf_path.name,
            use_raw_prompt=True,
            base_model_id="Qwen/Qwen3-1.7B",
            base_revision="70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
            quantization=qtype,
        )
        backend = _TimingWrapperBackend(inner)
        split_metrics: dict[str, Any] = {}
        total_k = 0
        total_n = 0
        for split_key, ds_path in (
            ("real_v2", "data/test_real_v2/test_real_v2.csv"),
            ("real", "data/test_real/test_real_DRAFT.csv"),
        ):
            m = evaluate(
                backend=backend,
                dataset_path=ds_path,
                run_name=f"local_{qkey}_{split_key}",
                results_root=out_root,
                seed=42,
                max_tokens=96,
                few_shot=0,
                batch_size=1,
                limit=limit,
                resume=True,
                formula_timeout=formula_timeout,
            )
            ov = m["overall"]
            n = int(ov["n"])
            k = round(float(ov["execution_accuracy"]) * n)
            lo, hi = wilson_ci(k, n)
            split_metrics[split_key] = {
                "n": n,
                "k": k,
                "execution_accuracy": ov["execution_accuracy"],
                "wilson_95_ci": [lo, hi],
                "syntax_valid_rate": ov["syntax_valid_rate"],
                "exact_match_rate": ov["exact_match_rate"],
                "avg_latency_ms": ov["avg_latency_ms"],
            }
            total_k += k
            total_n += n
    finally:
        peak_rss_mb = sampler.stop()
        mem_min_avail = get_memory_mb()["available_mb"]
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    comb_acc = round(total_k / total_n, 4) if total_n else 0.0
    comb_ci = list(wilson_ci(total_k, total_n))
    return {
        "status": "ok",
        "engine": "llama.cpp (llama-server)",
        "quant_key": qkey,
        "quant_type": qtype,
        "filename": gguf_path.name,
        "file_size_mb": round(gguf_path.stat().st_size / (1024 * 1024), 2),
        "load_time_s": load_time_s,
        "peak_ram_mb": peak_rss_mb
        if peak_rss_mb > 0
        else round(max(0.0, mem_before - mem_min_avail), 1),
        "gen_tokens_per_s": round(statistics.mean(backend.gen_tps), 2) if backend.gen_tps else None,
        "prompt_tokens_per_s": (
            round(statistics.mean(backend.prompt_tps), 2) if backend.prompt_tps else None
        ),
        "subset_n": total_n,
        "subset_k": total_k,
        "subset_execution_accuracy": comb_acc,
        "subset_wilson_95_ci": comb_ci,
        "splits": split_metrics,
    }


def _benchmark_with_ollama(
    gguf_path: Path,
    *,
    qkey: str,
    qtype: str,
    out_root: Path,
    limit: int | None,
    formula_timeout: float,
) -> dict[str, Any]:
    from src.eval.prompt_parity import render_modelfile

    ollama_exe = shutil.which("ollama")
    assert ollama_exe is not None
    tag = f"formulalm-v2-{qkey}"
    modelfile_p = gguf_path.parent / f"Modelfile.{qkey}.tmp"
    modelfile_p.write_text(render_modelfile(gguf_path.name), encoding="utf-8")
    try:
        subprocess.run(
            [ollama_exe, "create", tag, "-f", str(modelfile_p)],
            cwd=str(gguf_path.parent),
            check=True,
        )
    finally:
        if modelfile_p.exists():
            modelfile_p.unlink()

    mem_before = get_memory_mb()["available_mb"]
    t0 = time.perf_counter()
    # Warm / cold load probe + measure eval_count / eval_duration directly.
    warm = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": tag,
            "messages": [
                {
                    "role": "user",
                    "content": "Sheet: s (rows 2..5)\nColumns:\nA: X (integer)\n\nRequest: sum X",
                }
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 32, "seed": 42},
        },
        timeout=180,
    )
    warm.raise_for_status()
    wdata = warm.json()
    load_time_s = round(
        float(wdata.get("load_duration", 0)) / 1e9
        if wdata.get("load_duration")
        else (time.perf_counter() - t0),
        2,
    )
    gen_tps_samples: list[float] = []
    if wdata.get("eval_count") and wdata.get("eval_duration"):
        gen_tps_samples.append(float(wdata["eval_count"]) / (float(wdata["eval_duration"]) / 1e9))

    # Measure loaded model RAM via `ollama ps` / available RAM delta.
    mem_loaded = get_memory_mb()["available_mb"]
    peak_ram_mb = round(max(0.0, mem_before - mem_loaded), 1)

    backend = OllamaBackend(tag)
    split_metrics: dict[str, Any] = {}
    total_k = 0
    total_n = 0
    for split_key, ds_path in (
        ("real_v2", "data/test_real_v2/test_real_v2.csv"),
        ("real", "data/test_real/test_real_DRAFT.csv"),
    ):
        m = evaluate(
            backend=backend,
            dataset_path=ds_path,
            run_name=f"local_{qkey}_{split_key}",
            results_root=out_root,
            seed=42,
            max_tokens=96,
            few_shot=0,
            batch_size=1,
            limit=limit,
            resume=True,
            formula_timeout=formula_timeout,
        )
        ov = m["overall"]
        n = int(ov["n"])
        k = round(float(ov["execution_accuracy"]) * n)
        lo, hi = wilson_ci(k, n)
        split_metrics[split_key] = {
            "n": n,
            "k": k,
            "execution_accuracy": ov["execution_accuracy"],
            "wilson_95_ci": [lo, hi],
            "syntax_valid_rate": ov["syntax_valid_rate"],
            "exact_match_rate": ov["exact_match_rate"],
            "avg_latency_ms": ov["avg_latency_ms"],
        }
        total_k += k
        total_n += n

    comb_acc = round(total_k / total_n, 4) if total_n else 0.0
    comb_ci = list(wilson_ci(total_k, total_n))
    return {
        "status": "ok",
        "engine": "ollama",
        "quant_key": qkey,
        "quant_type": qtype,
        "filename": gguf_path.name,
        "file_size_mb": round(gguf_path.stat().st_size / (1024 * 1024), 2),
        "load_time_s": load_time_s,
        "peak_ram_mb": peak_ram_mb,
        "gen_tokens_per_s": round(statistics.mean(gen_tps_samples), 2) if gen_tps_samples else None,
        "prompt_tokens_per_s": None,
        "subset_n": total_n,
        "subset_k": total_k,
        "subset_execution_accuracy": comb_acc,
        "subset_wilson_95_ci": comb_ci,
        "splits": split_metrics,
    }


def render_local_benchmark_md(report: dict[str, Any]) -> str:
    env = report["environment"]
    lines = [
        "# FormulaLM Local Laptop Benchmark",
        "",
        f"- **OS:** {env['os']}",
        f"- **CPU:** {env['processor']} ({env['cpu_threads']} threads)",
        (
            f"- **RAM at start:** {env['ram_available_mb']:.0f} MB free / "
            f"{env['ram_total_mb']:.0f} MB total"
        ),
        f"- **Free disk:** {env['disk_free_gb']:.1f} GB",
        "",
        (
            "| Quant | Status | Engine | Size (MB) | Load (s) | Peak RAM (MB) | "
            "Gen tok/s | Local Subset Exec. Acc (95% CI) |"
        ),
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in report["results"]:
        if row["status"] != "ok":
            lines.append(
                f"| `{row['quant_type']}` | `{row['status']}` | — | "
                f"{row.get('file_size_mb', '—')} | — | — | — | {row.get('reason', '')} |"
            )
            continue
        ci = row["subset_wilson_95_ci"]
        tps = f"{row['gen_tokens_per_s']:.1f}" if row.get("gen_tokens_per_s") else "—"
        acc_pct = 100 * row["subset_execution_accuracy"]
        lines.append(
            f"| `{row['quant_type']}` | ok | {row['engine']} | {row['file_size_mb']:.1f} | "
            f"{row['load_time_s']:.2f} | {row['peak_ram_mb']:.0f} | {tps} | "
            f"**{acc_pct:.1f}%** ({row['subset_k']}/{row['subset_n']}, "
            f"[{100 * ci[0]:.1f}%, {100 * ci[1]:.1f}%]) |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models-dir",
        default="models/gguf_v2",
        help="Directory containing downloaded formulalm-qwen3-1.7b-v2-*.gguf files",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "llamacpp", "ollama"),
        default="auto",
        help="Local runtime to use (auto prefers llama-server, then ollama)",
    )
    parser.add_argument(
        "--quants",
        nargs="+",
        default=["q4_k_m", "q5_k_m", "q8_0"],
        choices=("q4_k_m", "q5_k_m", "q8_0"),
        help="Quantizations to benchmark in order",
    )
    parser.add_argument("--out-dir", default="results/local_benchmark")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    parser.add_argument(
        "--limit", type=int, default=None, help="Optional per-split limit for smoke"
    )
    parser.add_argument("--formula-timeout", type=float, default=15.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check hardware, installed runtimes, close-apps checklist and RAM fit",
    )
    args = parser.parse_args(argv)

    env = check_local_environment()
    print("=== Local Hardware & Runtime Check ===")
    print(f"OS:   {env['os']}")
    print(f"CPU:  {env['processor']} ({env['cpu_threads']} logical CPUs)")
    print(f"RAM:  {env['ram_available_mb']:.0f} MB free / {env['ram_total_mb']:.0f} MB total")
    print(f"Disk: {env['disk_free_gb']:.1f} GB free")
    for rname, rinfo in env["runtimes"].items():
        status = f"INSTALLED ({rinfo['version']})" if rinfo["installed"] else "NOT FOUND"
        print(f"  {rname:12s}: {status}")

    print("\n=== Close Before Running (8 GB RAM Laptop Checklist) ===")
    for idx, item in enumerate(CLOSE_BEFORE_RUNNING_CHECKLIST, start=1):
        print(f"  {idx}. {item}")

    has_llama = env["runtimes"]["llama_server"]["installed"]
    has_ollama = env["runtimes"]["ollama"]["installed"]
    chosen_engine: str | None = None
    if args.engine == "llamacpp":
        chosen_engine = "llamacpp" if has_llama else None
    elif args.engine == "ollama":
        chosen_engine = "ollama" if has_ollama else None
    else:
        chosen_engine = "llamacpp" if has_llama else ("ollama" if has_ollama else None)

    if chosen_engine is None:
        print("\n" + install_instructions_text())
        if not args.dry_run:
            return 2

    models_dir = Path(args.models_dir)
    qmap = {k: (qt, fn) for k, qt, fn in DEFAULT_QUANTS}
    out_root = Path(args.out_dir)
    results: list[dict[str, Any]] = []

    print(f"\n=== Quantization Memory-Fit & Benchmark ({models_dir}) ===")
    for qkey in args.quants:
        qtype, fname = qmap[qkey]
        gguf_path = models_dir / fname
        if not gguf_path.is_file():
            entry = {
                "status": "missing_file",
                "quant_key": qkey,
                "quant_type": qtype,
                "filename": fname,
                "reason": f"GGUF file not found at {gguf_path}",
            }
            print(f"  [{qtype}] SKIPPED — {entry['reason']}")
            results.append(entry)
            continue

        size_mb = gguf_path.stat().st_size / (1024 * 1024)
        avail_mb = get_memory_mb()["available_mb"]
        fit = check_memory_fit(size_mb, avail_mb)
        if not fit["fits"]:
            entry = {
                "status": "skipped_insufficient_ram",
                "quant_key": qkey,
                "quant_type": qtype,
                "filename": fname,
                **fit,
            }
            print(f"  [{qtype}] SKIPPED (RAM safety) — {fit['reason']}")
            results.append(entry)
            continue

        if args.dry_run:
            entry = {
                "status": "dry_run_fits",
                "quant_key": qkey,
                "quant_type": qtype,
                "filename": fname,
                **fit,
            }
            print(f"  [{qtype}] DRY-RUN OK — {fit['reason']}")
            results.append(entry)
            continue

        print(f"  [{qtype}] Running on {chosen_engine} ({fit['reason']})...", flush=True)
        if chosen_engine == "llamacpp":
            rec = _benchmark_with_llamacpp(
                gguf_path,
                qkey=qkey,
                qtype=qtype,
                out_root=out_root,
                port=args.port,
                threads=args.threads,
                limit=args.limit,
                formula_timeout=args.formula_timeout,
            )
        else:
            rec = _benchmark_with_ollama(
                gguf_path,
                qkey=qkey,
                qtype=qtype,
                out_root=out_root,
                limit=args.limit,
                formula_timeout=args.formula_timeout,
            )
        results.append(rec)
        sub_pct = 100 * rec["subset_execution_accuracy"]
        print(
            f"  [{qtype}] DONE | load={rec['load_time_s']}s | peak_ram={rec['peak_ram_mb']}MB | "
            f"tps={rec['gen_tokens_per_s']} | subset_exec={sub_pct:.1f}%",
            flush=True,
        )

    if not args.dry_run:
        out_root.mkdir(parents=True, exist_ok=True)
        payload = {"environment": env, "results": results}
        (out_root / "local_benchmark.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        md = render_local_benchmark_md(payload)
        (out_root / "local_benchmark.md").write_text(md, encoding="utf-8")
        print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
