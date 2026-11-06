import json

import pdfplumber
from conftest import DATASET

from kid_analyst.generatore import crea_prodotti, genera_dataset, isin
from kid_analyst.schema import TipoProdotto


def _isin_valido(codice: str) -> bool:
    cifre = "".join(str(int(c, 36)) for c in codice[:-1])
    somma = 0
    for i, c in enumerate(reversed(cifre)):
        n = int(c) * (2 if i % 2 == 0 else 1)
        somma += n // 10 + n % 10
    return (10 - somma % 10) % 10 == int(codice[-1])


def test_isin_noti():
    assert _isin_valido("IT0003132476")  # ENI
    assert _isin_valido("US0378331005")  # Apple
    import random
    assert all(_isin_valido(isin("LU", random.Random(i))) for i in range(50))


def test_valori_coerenti():
    for k in crea_prodotti():
        d, c = k.dati, k.dati.costi
        assert 1 <= d.sri <= 7
        s = d.scenari
        assert s.stress_pct < s.sfavorevole_pct < s.moderato_pct < s.favorevole_pct
        correnti = c.gestione_pct + c.transazione_pct + c.performance_pct
        atteso = correnti + (c.ingresso_pct + c.uscita_pct) / d.periodo_detenzione_anni
        assert abs(c.incidenza_annua_pct - atteso) < 0.006
        if d.tipo is TipoProdotto.certificato:
            assert c.gestione_pct == 0 and k.data_scadenza is not None
        if d.tipo is TipoProdotto.etf:
            assert c.ingresso_pct == 0


def test_dataset_versionato_riproducibile(tmp_path):
    genera_dataset(tmp_path)
    assert (tmp_path / "indice.json").read_text() == (DATASET / "indice.json").read_text()
    for f in (DATASET / "attesi").glob("*.json"):
        assert json.loads((tmp_path / "attesi" / f.name).read_text()) == json.loads(f.read_text())
    assert (tmp_path / "kid" / "kid_01.pdf").read_bytes() == (DATASET / "kid" / "kid_01.pdf").read_bytes()


def test_tre_pagine_e_tre_impaginazioni(dataset):
    assert len(dataset) == 30
    assert {v["impaginazione"] for v, _, _ in dataset} == {"tabellare", "discorsivo", "grafico"}
    for _, doc, _ in dataset:
        assert len(doc.pagine) == 3


def test_scala_sri_solo_grafica(dataset):
    """Nell'impaginazione "grafico" l'SRI non è scritto nel testo: solo la casella evidenziata lo indica."""
    for voce, doc, atteso in dataset:
        if voce["impaginazione"] == "grafico":
            assert "1 2 3 4 5 6 7" in doc.pagine[1].testo
            assert f"{atteso.sri} su 7" not in doc.testo
            with pdfplumber.open(DATASET / "kid" / f"{voce['codice']}.pdf") as pdf:
                piene = [r for r in pdf.pages[1].rects if r.get("non_stroking_color") not in (None, (1, 1, 1))]
            assert piene, "la casella evidenziata deve essere un rettangolo pieno"
