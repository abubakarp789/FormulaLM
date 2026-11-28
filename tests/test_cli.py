"""Tests for the one-command FormulaLM CLI (`src/formulalm/cli.py`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from formulalm.cli import (
    assert_localhost_url,
    main,
    normalize_inline_schema,
    run_cli_request,
)


class _StubBackend:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen_messages: list[dict[str, str]] = []

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        seed: int,
    ) -> str:
        del max_tokens, seed
        self.seen_messages = messages
        return self.reply


def _make_sample_xlsx(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sales"
    ws.append(["Region", "Units", "Revenue"])
    ws.append(["North", 10, 500])
    ws.append(["South", 5, 250])
    ws.append(["North", 8, 400])
    wb.save(path)
    wb.close()
    return path


def test_cli_xlsx_verify_and_inject_roundtrip(tmp_path: Path) -> None:
    src = _make_sample_xlsx(tmp_path / "sales.xlsx")
    out = tmp_path / "sales_out.xlsx"
    stub = _StubBackend('=SUMIF(A2:A4,"North",C2:C4)')

    res = run_cli_request(
        "Total Revenue for North",
        file_path=src,
        target_cell="E2",
        out_path=out,
        backend=stub,
    )
    assert res["ok"] is True
    assert res["formula"] == '=SUMIF(A2:A4,"North",C2:C4)'
    assert res["verified"] is True
    assert res["value"] == 900.0
    assert res["target_cell"] == "E2"
    assert out.is_file()

    wb = openpyxl.load_workbook(out, data_only=False)
    try:
        assert wb["Sales"]["E2"].value == '=SUMIF(A2:A4,"North",C2:C4)'
    finally:
        wb.close()


def test_cli_rejects_circular_reference(tmp_path: Path) -> None:
    src = _make_sample_xlsx(tmp_path / "sales.xlsx")
    out = tmp_path / "should_not_exist.xlsx"
    stub = _StubBackend("=E2+1")

    res = run_cli_request(
        "Increment E2",
        file_path=src,
        target_cell="E2",
        out_path=out,
        backend=stub,
    )
    assert res["ok"] is False
    assert "circular" in (res["error"] or "").lower()
    assert not out.exists()


def test_cli_schema_mode_and_json_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "formulalm.cli.OllamaBackend",
        lambda model, base_url: _StubBackend("=AVERAGE(C2:C50)"),
    )
    code = main(
        [
            "Average price",
            "--schema",
            "A:Product, B:Qty, C:Price (rows 2..50)",
            "--json",
        ]
    )
    assert code == 0
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["formula"] == "=AVERAGE(C2:C50)"
    assert payload["syntax_valid"] is True


def test_normalize_inline_schema() -> None:
    s = normalize_inline_schema("A:Region, B:Units (integer), C:Revenue (decimal) (rows 2..20)")
    assert "Sheet: Sheet1 (rows 2..20)" in s
    assert "A: Region (text)" in s
    assert "B: Units (integer)" in s
    assert "C: Revenue (decimal)" in s


def test_assert_localhost_blocks_remote_host() -> None:
    assert assert_localhost_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    with pytest.raises(ValueError, match="blocked"):
        assert_localhost_url("https://api.openai.com/v1")
