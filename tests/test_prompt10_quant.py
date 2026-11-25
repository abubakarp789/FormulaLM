"""Tests for PROMPT 10: parity, Modelfiles, llama.cpp backend, RAM gate & quant comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from formulalm.config import REPO_ROOT
from scripts.benchmark_local import check_memory_fit, estimate_required_ram_mb
from src.data.build_dataset import SYSTEM_PROMPT
from src.eval.compare_quant import build_quant_comparison, render_quant_comparison_md
from src.eval.prompt_parity import (
    NON_THINKING_GENERATION_PREFIX,
    compare_parity_records,
    render_modelfile,
    render_parity_markdown,
    render_qwen3_non_thinking_prompt,
)
from src.eval.run_eval import LlamaCppBackend


def test_render_qwen3_non_thinking_prompt_and_modelfiles_match_training():
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "Sheet: demo (rows 2..5)\nColumns:\nA: X (integer)\n\nRequest: sum X",
        },
    ]
    prompt = render_qwen3_non_thinking_prompt(msgs)
    assert prompt.startswith(f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n")
    assert "<|im_start|>user\nSheet: demo" in prompt
    assert prompt.endswith(NON_THINKING_GENERATION_PREFIX)

    # All committed deploy/Modelfile* must reproduce exact SYSTEM_PROMPT and non-thinking template.
    expected_map = {
        "Modelfile": "formulalm-qwen3-1.7b-v2-q5_k_m.gguf",
        "Modelfile.Q4_K_M": "formulalm-qwen3-1.7b-v2-q4_k_m.gguf",
        "Modelfile.Q5_K_M": "formulalm-qwen3-1.7b-v2-q5_k_m.gguf",
        "Modelfile.Q8_0": "formulalm-qwen3-1.7b-v2-q8_0.gguf",
    }
    for fname, gguf in expected_map.items():
        text = (REPO_ROOT / "deploy" / fname).read_text(encoding="utf-8")
        assert text == render_modelfile(gguf)
        assert SYSTEM_PROMPT in text
        assert "<think>\n\n</think>\n\n" in text
        assert "PARAMETER temperature 0" in text


def test_llamacpp_backend_uses_raw_non_thinking_prompt_and_records_provenance(monkeypatch):
    captured: dict[str, Any] = {}

    class _FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {
                "content": "=SUM(A2:A5)",
                "timings": {"predicted_per_second": 18.5, "prompt_per_second": 95.0},
            }

    def _fake_post(url: str, *, json: dict[str, Any], timeout: float):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return _FakeResp()

    monkeypatch.setattr("src.eval.run_eval.requests.post", _fake_post)
    be = LlamaCppBackend(
        base_url="http://127.0.0.1:8080",
        model="formulalm-qwen3-1.7b-v2-q4_k_m.gguf",
        base_model_id="Qwen/Qwen3-1.7B",
        base_revision="70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        quantization="Q4_K_M",
    )
    out = be.generate(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "sum A"}],
        max_tokens=96,
        seed=42,
    )
    assert out == "=SUM(A2:A5)"
    assert captured["url"].endswith("/completion")
    assert captured["payload"]["prompt"].endswith(NON_THINKING_GENERATION_PREFIX)
    assert captured["payload"]["temperature"] == 0.0
    assert be.last_timings["predicted_per_second"] == 18.5
    prov = be.provenance()
    assert prov["quantization"] == "Q4_K_M"
    assert prov["enable_thinking"] is False
    assert prov["prompt_mode"] == "raw_qwen3_non_thinking"


def test_parity_comparison_reports_exact_match_and_diffs():
    ref = [
        {
            "id": "r1",
            "sheet_id": "s1",
            "request": "sum A",
            "reference_formula": "=SUM(A2:A5)",
            "raw_output": "=SUM(A2:A5)",
            "extracted_formula": "=SUM(A2:A5)",
            "exec_ok": True,
            "predicted_value": "10",
            "exec_correct": True,
        },
        {
            "id": "r2",
            "sheet_id": "s1",
            "request": "avg A",
            "reference_formula": "=AVERAGE(A2:A5)",
            "raw_output": "=AVERAGE(A2:A5)",
            "extracted_formula": "=AVERAGE(A2:A5)",
            "exec_ok": True,
            "predicted_value": "2.5",
            "exec_correct": True,
        },
    ]
    cand = [
        dict(ref[0]),
        dict(
            ref[1],
            raw_output="=SUM(A2:A5)",
            extracted_formula="=SUM(A2:A5)",
            predicted_value="10",
            exec_correct=False,
        ),
    ]
    rep = compare_parity_records(ref, cand)
    assert rep["n"] == 2
    assert rep["raw_match_count"] == 1
    assert rep["diff_count"] == 1
    md = render_parity_markdown(rep)
    assert "1/2" in md and "r2" in md


def test_local_memory_fit_gate_prevents_oom():
    # Q4_K_M (~1100 MB) -> requires ~1725 MB; with 2500 MB free (2150 MB safe budget) -> fits
    assert estimate_required_ram_mb(1100.0) == 1725.0
    ok = check_memory_fit(1100.0, available_ram_mb=2500.0)
    assert ok["fits"] is True

    # With only 900 MB free -> MUST NOT fit (prevents freezing 8 GB laptop)
    no = check_memory_fit(1100.0, available_ram_mb=900.0)
    assert no["fits"] is False
    assert "does NOT fit" in no["reason"]


def _write_quant_run(root: Path, run_name: str, k: int, n: int) -> None:
    d = root / run_name
    d.mkdir(parents=True, exist_ok=True)
    preds = [{"id": f"e{i}", "category": "aggregation", "exec_correct": i < k} for i in range(n)]
    (d / "predictions.jsonl").write_text(
        "\n".join(json.dumps(p) for p in preds) + "\n", encoding="utf-8"
    )
    metrics = {
        "run_name": run_name,
        "overall": {
            "n": n,
            "syntax_valid_rate": 1.0,
            "exec_ok_rate": 1.0,
            "execution_accuracy": round(k / n, 4),
            "exact_match_rate": round(k / n, 4),
            "raw_format_ok_rate": 1.0,
            "avg_latency_ms": 100.0,
        },
        "by_category": {},
    }
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")


def test_compare_quant_recommends_smallest_within_noise_and_respects_ram_skip(tmp_path: Path):
    # Empty results -> PENDING
    pending = build_quant_comparison(tmp_path)
    assert pending["recommendation"]["status"] == "PENDING"

    # Populate artifacts + F16 + Q8_0 + Q5_K_M + Q4_K_M
    (tmp_path / "quant_artifacts.json").write_text(
        json.dumps(
            {
                "files": {
                    "f16": {"size_mb": 3400.0},
                    "q8_0": {"size_mb": 1820.0},
                    "q5_k_m": {"size_mb": 1280.0},
                    "q4_k_m": {"size_mb": 1100.0},
                }
            }
        ),
        encoding="utf-8",
    )
    # F16 reference
    _write_quant_run(tmp_path, "quant_f16_val", 498, 500)
    _write_quant_run(tmp_path, "quant_f16_real_v2", 44, 50)
    _write_quant_run(tmp_path, "quant_f16_real", 75, 80)
    _write_quant_run(tmp_path, "quant_f16_synthetic", 494, 500)

    # Q8_0 and Q5_K_M match F16 within noise; Q4_K_M degrades sharply (-5 pp on val)
    for q, (kv, kr2, kr, ks) in (
        ("q8_0", (498, 44, 75, 493)),
        ("q5_k_m", (496, 44, 74, 492)),
        ("q4_k_m", (470, 40, 70, 470)),
    ):
        _write_quant_run(tmp_path, f"quant_{q}_val", kv, 500)
        _write_quant_run(tmp_path, f"quant_{q}_real_v2", kr2, 50)
        _write_quant_run(tmp_path, f"quant_{q}_real", kr, 80)
        _write_quant_run(tmp_path, f"quant_{q}_synthetic", ks, 500)

    comp = build_quant_comparison(tmp_path)
    assert comp["recommendation"]["status"] == "RECOMMENDED"
    assert comp["recommendation"]["recommended"] == "quant_q5_k_m"
    md = render_quant_comparison_md(comp)
    assert "informed by v1 error analysis" in md
    assert "Q5_K_M" in md


def test_merge_quantize_notebook_is_valid_and_gates_hf_upload():
    nb = json.loads(
        (REPO_ROOT / "notebooks" / "05_merge_quantize.ipynb").read_text(encoding="utf-8")
    )
    assert nb["nbformat"] == 4
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e" in src
    assert "e2dd7e8115406ffcdbbdfa60d6f2f10b4aaf2595" in src
    assert "PUSH_GGUF_TO_HF = False" in src
    assert "verify_tokenizer_parity" in src
    assert "compare_quant" in src
