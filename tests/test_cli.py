import json

from conftest import DATASET

from kid_analyst.cli import main


def test_valuta_regole(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["valuta", "--uscita", str(tmp_path)])
    assert "| regole |" in capsys.readouterr().out
    sintesi = json.loads((tmp_path / "regole.json").read_text())["sintesi"]
    assert sintesi["documenti"] == 30 and sintesi["costo_usd"] == 0


def test_confronta_con_profilo(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["confronta", str(DATASET / "kid" / "kid_01.pdf"), str(DATASET / "kid" / "kid_04.pdf"),
          "--profilo", str(DATASET / "profili" / "anna.json")])
    out = capsys.readouterr().out
    assert "Anna Esempio" in out and " 1. [" in out and " 2. [" in out


def test_motore_claude_senza_chiave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import pytest
    with pytest.raises(SystemExit):
        main(["estrai", str(DATASET / "kid" / "kid_01.pdf"), "--motore", "claude-haiku-5-5:testo:low"])
