"""Qwen3 non-thinking prompt rendering and HF-vs-GGUF parity verification.

Guarantees byte-for-byte prompt parity between:
- Hugging Face Qwen3 tokenizer (``enable_thinking=False``)
- llama.cpp ``/completion`` and ``llama-cpp-python`` raw completion prompts
- Ollama ``Modelfile`` templates in ``deploy/``

CLI usage (compare saved prediction JSONLs or two live backends on 20 fixed examples):
    uv run python -m src.eval.prompt_parity \
        --ref results/quant_parity/hf_merged_fp16_20.jsonl \
        --cand results/quant_parity/gguf_f16_20.jsonl \
        --out results/quant_parity/parity_report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from formulalm.config import REPO_ROOT
from src.data.build_dataset import SYSTEM_PROMPT
from src.eval.executor import run_formula
from src.eval.normalize import exact_match, values_equal

NON_THINKING_GENERATION_PREFIX = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
STOP_TOKENS: tuple[str, ...] = ("<|im_end|>", "<|endoftext|>", "<|im_start|>")


def render_qwen3_non_thinking_prompt(messages: list[dict[str, str]]) -> str:
    """Render chat messages identically to Qwen3's chat template with ``enable_thinking=False``."""
    parts: list[str] = []
    for idx, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            parts.append(f"<|im_start|>system\n{content}<|im_end|>\n")
        elif role == "user":
            parts.append(f"<|im_start|>user\n{content}<|im_end|>\n")
        elif role == "assistant":
            is_last = idx == len(messages) - 1
            if is_last:
                parts.append(f"{NON_THINKING_GENERATION_PREFIX}{content}<|im_end|>\n")
            else:
                parts.append(f"<|im_start|>assistant\n{content}<|im_end|>\n")
        else:
            raise ValueError(f"Unsupported chat role: {role!r}")

    parts.append(NON_THINKING_GENERATION_PREFIX)
    return "".join(parts)


def verify_tokenizer_parity(
    tokenizer: Any,
    sample_messages: list[list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Assert ``render_qwen3_non_thinking_prompt`` matches ``tokenizer.apply_chat_template``."""
    if sample_messages is None:
        sample_messages = [
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Sheet: demo (rows 2..10)\nColumns:\nA: Amount (decimal)\n\n"
                    "Request: Total Amount",
                },
            ]
        ]

    mismatches: list[dict[str, Any]] = []
    for i, msgs in enumerate(sample_messages):
        expected = str(
            tokenizer.apply_chat_template(
                msgs,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        )
        ours = render_qwen3_non_thinking_prompt(msgs)
        if ours != expected:
            mismatches.append({"index": i, "expected": expected, "actual": ours})
    return {
        "checked": len(sample_messages),
        "exact_match": len(mismatches) == 0,
        "mismatches": mismatches,
    }


def load_parity_records(path: str | Path) -> list[dict[str, Any]]:
    """Load JSONL records written by ``run_parity_eval``."""
    p = Path(path)
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_parity_capture(
    backend: Any,
    *,
    dataset_path: str | Path = "data/test_real_v2/test_real_v2.csv",
    n: int = 20,
    seed: int = 42,
    max_tokens: int = 96,
    out_jsonl: str | Path | None = None,
    formula_timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Run ``backend`` on the first ``n`` fixed examples and capture raw/extracted/exec outputs."""
    from src.eval.run_eval import build_eval_messages, extract_formula, load_eval_examples

    examples, xlsx_by_sheet = load_eval_examples(dataset_path)
    subset = examples[:n]
    records: list[dict[str, Any]] = []
    for ex in subset:
        msgs = build_eval_messages(ex, few_shot=0)
        raw = backend.generate(msgs, max_tokens=max_tokens, seed=seed, example=ex)
        extracted = extract_formula(raw)
        res = run_formula(extracted, xlsx_by_sheet[ex.sheet_id], timeout=formula_timeout)
        exec_correct = res.ok and values_equal(res.value, ex.expected_value)
        records.append(
            {
                "id": ex.id,
                "sheet_id": ex.sheet_id,
                "category": ex.category,
                "difficulty": ex.difficulty,
                "request": ex.request,
                "reference_formula": ex.reference_formula,
                "raw_output": raw,
                "extracted_formula": extracted,
                "exec_ok": res.ok,
                "predicted_value": str(res.value) if res.value is not None else None,
                "expected_value": str(ex.expected_value) if ex.expected_value is not None else None,
                "exec_correct": exec_correct,
                "error_type": res.error_type,
            }
        )
    if out_jsonl is not None:
        out_p = Path(out_jsonl)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
    return records


def compare_parity_records(
    ref_records: list[dict[str, Any]],
    cand_records: list[dict[str, Any]],
    *,
    ref_label: str = "HF Merged FP16",
    cand_label: str = "GGUF F16",
) -> dict[str, Any]:
    """Compare two 20-example runs and report raw, formula, and execution-value agreement."""
    cand_by_id = {r["id"]: r for r in cand_records}
    n = 0
    raw_matches = 0
    formula_matches = 0
    value_matches = 0
    ref_correct = 0
    cand_correct = 0
    diffs: list[dict[str, Any]] = []

    for ref in ref_records:
        cid = ref["id"]
        if cid not in cand_by_id:
            continue
        cand = cand_by_id[cid]
        n += 1
        ref_correct += int(bool(ref.get("exec_correct")))
        cand_correct += int(bool(cand.get("exec_correct")))

        raw_eq = (ref.get("raw_output") or "").strip() == (cand.get("raw_output") or "").strip()
        fml_eq = exact_match(
            str(ref.get("extracted_formula") or ""),
            str(cand.get("extracted_formula") or ""),
        )
        val_eq = bool(ref.get("exec_ok")) == bool(cand.get("exec_ok")) and ref.get(
            "predicted_value"
        ) == cand.get("predicted_value")
        raw_matches += int(raw_eq)
        formula_matches += int(fml_eq)
        value_matches += int(val_eq)

        if not (raw_eq and fml_eq and val_eq):
            diffs.append(
                {
                    "id": cid,
                    "sheet_id": ref.get("sheet_id"),
                    "request": ref.get("request"),
                    "reference_formula": ref.get("reference_formula"),
                    "ref_raw": ref.get("raw_output"),
                    "cand_raw": cand.get("raw_output"),
                    "ref_formula": ref.get("extracted_formula"),
                    "cand_formula": cand.get("extracted_formula"),
                    "ref_exec_correct": ref.get("exec_correct"),
                    "cand_exec_correct": cand.get("exec_correct"),
                    "raw_eq": raw_eq,
                    "formula_eq": fml_eq,
                    "value_eq": val_eq,
                }
            )

    return {
        "ref_label": ref_label,
        "cand_label": cand_label,
        "n": n,
        "raw_match_count": raw_matches,
        "raw_match_rate": round(raw_matches / n, 4) if n else 0.0,
        "formula_match_count": formula_matches,
        "formula_match_rate": round(formula_matches / n, 4) if n else 0.0,
        "value_match_count": value_matches,
        "value_match_rate": round(value_matches / n, 4) if n else 0.0,
        "ref_exec_correct": ref_correct,
        "cand_exec_correct": cand_correct,
        "diff_count": len(diffs),
        "diffs": diffs,
    }


def render_parity_markdown(report: dict[str, Any]) -> str:
    n = report["n"]
    lines = [
        f"# Prompt-Format & Output Parity Report: {report['ref_label']} vs {report['cand_label']}",
        "",
        (
            f"Evaluated on **{n} fixed examples** "
            "(`temperature=0`, `seed=42`, `enable_thinking=False`)."
        ),
        "",
        "| Metric | Count | Rate |",
        "|---|---:|---:|",
        f"| Raw output exact match | {report['raw_match_count']}/{n} | "
        f"{100.0 * report['raw_match_rate']:.1f}% |",
        f"| Normalized formula match | {report['formula_match_count']}/{n} | "
        f"{100.0 * report['formula_match_rate']:.1f}% |",
        f"| Executed value agreement | {report['value_match_count']}/{n} | "
        f"{100.0 * report['value_match_rate']:.1f}% |",
        f"| {report['ref_label']} execution accuracy | {report['ref_exec_correct']}/{n} | "
        f"{(100.0 * report['ref_exec_correct'] / n) if n else 0.0:.1f}% |",
        f"| {report['cand_label']} execution accuracy | {report['cand_exec_correct']}/{n} | "
        f"{(100.0 * report['cand_exec_correct'] / n) if n else 0.0:.1f}% |",
        "",
    ]
    if not report["diffs"]:
        lines.append("**Result:** 100% parity — zero differences across all 20 fixed examples.")
    else:
        lines.append(f"## Differences ({report['diff_count']} example(s))")
        lines.append("")
        for d in report["diffs"]:
            lines.append(f"- **`{d['id']}`** (`{d['sheet_id']}`): {d['request']}")
            lines.append(f"  - Ground truth: `{d['reference_formula']}`")
            lines.append(
                f"  - {report['ref_label']}: `{d['ref_raw']}` "
                f"(exec_correct={d['ref_exec_correct']})"
            )
            lines.append(
                f"  - {report['cand_label']}: `{d['cand_raw']}` "
                f"(exec_correct={d['cand_exec_correct']})"
            )
    return "\n".join(lines) + "\n"


def render_modelfile(gguf_filename: str) -> str:
    """Generate an Ollama Modelfile that reproduces Qwen3 non-thinking training prompts exactly."""
    return (
        f"FROM ./{gguf_filename}\n\n"
        f'SYSTEM """{SYSTEM_PROMPT}"""\n\n'
        'TEMPLATE """{{- range $i, $_ := .Messages }}\n'
        "{{- $last := eq (len (slice $.Messages $i)) 1 -}}\n"
        '{{- if eq .Role "system" }}<|im_start|>system\n'
        "{{ .Content }}<|im_end|>\n"
        '{{ else if eq .Role "user" }}<|im_start|>user\n'
        "{{ .Content }}<|im_end|>\n"
        '{{ else if eq .Role "assistant" }}<|im_start|>assistant\n'
        "<think>\n\n"
        "</think>\n\n"
        "{{ .Content }}{{ if not $last }}<|im_end|>\n"
        "{{ end }}\n"
        "{{- end }}\n"
        '{{- if and $last (ne .Role "assistant") }}<|im_start|>assistant\n'
        "<think>\n\n"
        "</think>\n\n"
        "{{ end }}\n"
        '{{- end }}"""\n\n'
        'PARAMETER stop "<|im_start|>"\n'
        'PARAMETER stop "<|im_end|>"\n'
        'PARAMETER stop "<|endoftext|>"\n'
        "PARAMETER temperature 0\n"
        "PARAMETER num_ctx 2048\n"
        "PARAMETER num_predict 96\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True, help="Reference parity JSONL (e.g. HF merged FP16)")
    parser.add_argument("--cand", required=True, help="Candidate parity JSONL (e.g. GGUF F16)")
    parser.add_argument("--ref-label", default="HF Merged FP16")
    parser.add_argument("--cand-label", default="GGUF F16")
    parser.add_argument("--out", default=None, help="Output markdown report path")
    parser.add_argument("--json-out", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    rep = compare_parity_records(
        load_parity_records(args.ref),
        load_parity_records(args.cand),
        ref_label=args.ref_label,
        cand_label=args.cand_label,
    )
    md = render_parity_markdown(rep)
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")
    if args.json_out:
        jp = Path(args.json_out)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    _ = REPO_ROOT
    sys.exit(main())
