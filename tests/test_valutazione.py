from kid_analyst.schema import CAMPI
from kid_analyst.valutazione import confronta, corretto, tabella_markdown, valuta


def test_tolleranze():
    assert corretto("costi.gestione_pct", 1.25, 1.26)
    assert not corretto("costi.gestione_pct", 1.25, 1.27)
    assert corretto("periodo_detenzione_anni", 5.0, 5.04)
    assert not corretto("sri", 4, None)
    assert corretto("nome_prodotto", "Aurora Bilanciato – Classe A", "aurora  bilanciato - classe a")
    assert not corretto("isin", "IT0003132476", "IT0003132477")


def test_rapporto(dataset):
    voci = dataset[:6]

    def finto(doc):
        atteso = next(a for _, d, a in voci if d.codice == doc.codice)
        trovato = atteso.model_copy(deep=True)
        if doc.codice == voci[0][1].codice:
            trovato.sri = None
            trovato.costi.gestione_pct += 0.5
        if doc.codice == voci[1][1].codice:
            raise RuntimeError("PDF illeggibile")
        return trovato, 0.01

    errori = []
    r = valuta("finto", finto, voci, lambda c, e: errori.append(c))
    assert errori == [voci[1][1].codice]
    assert r.documenti[0].campi_corretti == len(CAMPI) - 2
    assert r.documenti[1].campi_corretti == 0 and "PDF illeggibile" in r.documenti[1].errore
    assert r.accuratezza == (6 * len(CAMPI) - 2 - len(CAMPI)) / (6 * len(CAMPI))
    assert r.documenti_perfetti == 4 / 6
    assert abs(r.per_campo()["sri"] - 4 / 6) < 1e-9
    assert abs(r.costo_usd - 0.05) < 1e-9
    assert "| finto |" in tabella_markdown([r])


def test_confronta_identici(dataset):
    _, _, a = dataset[0]
    assert confronta(a, a) == []
