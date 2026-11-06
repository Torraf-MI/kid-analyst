import json

from conftest import DATASET

from kid_analyst import estrattore_regole as er
from kid_analyst.confronto import ATTENZIONE, KO, OK, valuta_prodotti


def _profilo(nome):
    return json.loads((DATASET / "profili" / f"{nome}.json").read_text())


def _prodotti(dataset, n=12):
    return {d.codice: a for _, d, a in dataset[:n]}


def test_ordinati_per_costo(dataset):
    v = valuta_prodotti(_prodotti(dataset))
    costi = [x.costo_annuo_pct for x in v]
    assert costi == sorted(costi, reverse=True) and [x.rango_costo for x in v] == list(range(1, len(v) + 1))


def test_coerenza_con_il_profilo(dataset):
    lucia = _profilo("lucia")  # moderato: SRI massimo 3, orizzonte 4 anni, niente fondi né certificati
    for v in valuta_prodotti(_prodotti(dataset), lucia):
        per = {s.controllo: s.esito for s in v.segnalazioni}
        assert per["Rischio"] == (OK if v.dati.sri <= 3 else KO)
        assert per["Conoscenza ed esperienza"] == KO
        assert v.esito == KO
    giorgio = _profilo("giorgio")  # dinamico, certificati ammessi
    esiti = {v.codice: v for v in valuta_prodotti(_prodotti(dataset), giorgio)}
    assert any(v.esito == OK for v in esiti.values())
    for v in esiti.values():
        assert {s.controllo: s.esito for s in v.segnalazioni}["Conoscenza ed esperienza"] == OK


def test_prodotto_costoso_segnalato(dataset):
    prodotti = _prodotti(dataset, 30)
    fondi = sorted((a for a in prodotti.values() if a.tipo.value == "fondo"), key=lambda a: a.costi.incidenza_annua_pct)
    caro = fondi[-1].model_copy(deep=True)
    caro.costi.incidenza_annua_pct = 9.0
    prodotti["caro"] = caro
    v = {x.codice: x for x in valuta_prodotti(prodotti)}
    assert v["caro"].rango_costo == 1
    assert any(s.controllo == "Costi" and s.esito == ATTENZIONE for s in v["caro"].segnalazioni)


def test_dati_mancanti_segnalati(dataset):
    _, doc, _ = next(x for x in dataset if x[0]["impaginazione"] == "grafico")
    v = valuta_prodotti({doc.codice: er.estrai(doc)})[0]
    assert v.segnalazioni[0].controllo == "Dati" and "SRI" in v.segnalazioni[0].dettaglio
