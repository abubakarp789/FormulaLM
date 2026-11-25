"""Clean-folder post-publish verification for FormulaLM Q5_K_M GGUF + Ollama Modelfile.

Downloads ``formulalm-qwen3-1.7b-v2-q5_k_m.gguf`` and ``Modelfile`` from the published
Hugging Face (or ModelScope) repo into a brand-new temporary directory, verifies SHA-256
against ``results/quant_artifacts.json``, runs the exact Ollama quick-start from the model
card (``ollama create`` + query on the Mirehaven sales prompt), executes the returned Excel
formula on ``data/sheets/sales_retail_store.xlsx``, and verifies the computed value matches
the ground truth.

Usage (run AFTER publishing and confirming):
    uv run python scripts/verify_published_download.py --source hf
    uv run python scripts/verify_published_download.py --source modelscope
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from src.eval.executor import run_formula  # noqa: E402
from src.eval.normalize import values_equal  # noqa: E402
from src.eval.run_eval import extract_formula  # noqa: E402

PRIMARY_GGUF = "formulalm-qwen3-1.7b-v2-q5_k_m.gguf"
QUICKSTART_PROMPT = (
    "Sheet: sales_retail_store (rows 2..115)\n"
    "Columns:\n"
    "A: Receipt Code (text)\n"
    "B: Sale Date (date)\n"
    "C: Store Branch (category)\n"
    "D: Item Name (text)\n"
    "E: Quantity (integer)\n"
    "F: Net Amount (decimal)\n\n"
    "Request: Total Net Amount for the Mirehaven branch"
)
REFERENCE_FORMULA = '=SUMIF(C2:C115,"Mirehaven",F2:F115)'


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_url(url: str, dst: Path) -> None:
    print(f"Downloading {url} -> {dst.name}...", flush=True)
    urllib.request.urlretrieve(url, dst)


def verify_clean_download(
    *,
    source: str = "hf",
    repo_id: str = "abubakar56/formulalm-qwen3-1.7b-gguf",
    ollama_tag: str = "formulalm-verify",
    keep_tag: bool = False,
) -> dict[str, object]:
    ollama_exe = shutil.which("ollama")
    if not ollama_exe:
        raise RuntimeError("`ollama` binary not found on PATH.")

    art_path = REPO_ROOT / "results" / "quant_artifacts.json"
    expected_sha = json.loads(art_path.read_text(encoding="utf-8"))["files"]["q5_k_m"]["sha256"]

    with tempfile.TemporaryDirectory(prefix="formulalm_clean_verify_") as tdir:
        clean = Path(tdir)
        gguf_dst = clean / PRIMARY_GGUF
        mf_dst = clean / "Modelfile"

        if source == "hf":
            base = f"https://huggingface.co/{repo_id}/resolve/main"
            _download_url(f"{base}/{PRIMARY_GGUF}", gguf_dst)
            _download_url(f"{base}/Modelfile", mf_dst)
        elif source == "modelscope":
            base = f"https://modelscope.cn/models/{repo_id}/resolve/master"
            _download_url(f"{base}/{PRIMARY_GGUF}", gguf_dst)
            _download_url(f"{base}/Modelfile", mf_dst)
        else:
            raise ValueError(f"Unsupported source: {source!r}")

        actual_sha = sha256_file(gguf_dst)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"SHA-256 mismatch for {PRIMARY_GGUF}: expected {expected_sha}, got {actual_sha}"
            )
        print(
            f"SHA-256 verified: {actual_sha[:16]}... ({gguf_dst.stat().st_size / (1024**2):.2f} MB)"
        )

        mf_text = mf_dst.read_text(encoding="utf-8")
        if PRIMARY_GGUF not in mf_text:
            raise RuntimeError(f"Downloaded Modelfile does not reference {PRIMARY_GGUF}!")

        subprocess.run(
            [ollama_exe, "create", ollama_tag, "-f", "Modelfile"],
            cwd=str(clean),
            check=True,
        )
        try:
            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": ollama_tag,
                    "messages": [{"role": "user", "content": QUICKSTART_PROMPT}],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.0, "num_predict": 96, "seed": 42},
                },
                timeout=180,
            )
            resp.raise_for_status()
            raw = str(resp.json().get("message", {}).get("content", "")).strip()
        finally:
            try:
                requests.post(
                    "http://localhost:11434/api/generate",
                    json={"model": ollama_tag, "keep_alive": 0},
                    timeout=15,
                )
            except Exception:
                pass
            if not keep_tag:
                subprocess.run([ollama_exe, "rm", ollama_tag], check=False)

    extracted = extract_formula(raw)
    sheet_xlsx = REPO_ROOT / "data" / "sheets" / "sales_retail_store.xlsx"
    ref_res = run_formula(REFERENCE_FORMULA, sheet_xlsx, timeout=30.0)
    pred_res = run_formula(extracted, sheet_xlsx, timeout=30.0)
    ok = pred_res.ok and ref_res.ok and values_equal(pred_res.value, ref_res.value)

    report = {
        "source": source,
        "repo_id": repo_id,
        "sha256_ok": True,
        "raw_output": raw,
        "extracted_formula": extracted,
        "reference_formula": REFERENCE_FORMULA,
        "predicted_value": pred_res.value,
        "expected_value": ref_res.value,
        "exec_correct": ok,
    }
    print(json.dumps(report, indent=2))
    if not ok:
        raise RuntimeError(f"Verification failed: {report}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("hf", "modelscope"), default="hf")
    parser.add_argument("--repo-id", default="abubakar56/formulalm-qwen3-1.7b-gguf")
    parser.add_argument("--tag", default="formulalm-verify")
    parser.add_argument("--keep-tag", action="store_true")
    args = parser.parse_args(argv)
    verify_clean_download(
        source=args.source, repo_id=args.repo_id, ollama_tag=args.tag, keep_tag=args.keep_tag
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
