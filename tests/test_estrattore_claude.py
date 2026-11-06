import base64
import json

import pytest

from kid_analyst.costi_api import BudgetSuperato, Registro, costo
from kid_analyst.estrattore_claude import ErroreEstrazione, EstrattoreClaude


def _risposta(dati) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(dati.model_dump(mode="json"))}], "output_tokens": 800}


def test_richiesta_pdf_e_output_strutturato(dataset, api_finta, tmp_path):
    _, doc, atteso = dataset[2]
    api = api_finta([_risposta(atteso)])
    registro = Registro(budget_usd=1.0)
    e = EstrattoreClaude(api.client(), "claude-opus-5-5", "pdf", "low", registro, tmp_path)

    dati, speso = e.estrai(doc)

    assert dati == atteso
    assert speso == pytest.approx(costo("claude-opus-5-5", 3000, 800))
    percorsi = [p for p, _ in api.richieste]
    assert percorsi[0].endswith("/messages/count_tokens") and percorsi[1].endswith("/messages")
    corpo = api.messaggi[0]
    blocco = corpo["messages"][0]["content"][0]
    assert blocco["type"] == "document" and blocco["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(blocco["source"]["data"]) == doc.contenuto
    assert corpo["output_config"]["effort"] == "low"
    formato = corpo["output_config"]["format"]
    assert formato["type"] == "json_schema" and "costi" in formato["schema"]["properties"]
    assert "temperature" not in corpo

    # seconda volta: dalla cache, nessuna chiamata e costo zero
    dati2, speso2 = e.estrai(doc)
    assert dati2 == atteso and speso2 == 0 and len(api.richieste) == 2 and registro.da_cache == 1


def test_modalita_testo(dataset, api_finta):
    _, doc, atteso = dataset[0]
    api = api_finta([_risposta(atteso)])
    EstrattoreClaude(api.client(), "claude-haiku-5-5", "testo").estrai(doc)
    blocco = api.messaggi[0]["messages"][0]["content"][0]
    assert blocco["type"] == "text" and "[Pagina 3]" in blocco["text"]


def test_budget_controllato_prima_della_chiamata(dataset, api_finta):
    _, doc, atteso = dataset[0]
    api = api_finta([_risposta(atteso)], token_input=200_000)
    e = EstrattoreClaude(api.client(), "claude-opus-5-5", "pdf", registro=Registro(budget_usd=0.10))
    with pytest.raises(BudgetSuperato):
        e.estrai(doc)
    assert api.messaggi == []  # solo il conteggio dei token, nessuna chiamata a pagamento


def test_rifiuto(dataset, api_finta):
    _, doc, _ = dataset[0]
    api = api_finta([{"content": [], "stop_reason": "refusal"}])
    with pytest.raises(ErroreEstrazione):
        EstrattoreClaude(api.client()).estrai(doc)
