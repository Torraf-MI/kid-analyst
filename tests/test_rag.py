from kid_analyst import estrattore_regole as er
from kid_analyst import rag
from kid_analyst.costi_api import Registro


def _indice(dataset):
    docs = [d for _, d, _ in dataset]
    return rag.Indice(docs, {d.codice: a.nome_prodotto for _, d, a in dataset}), docs


def test_ricerca_nel_documento_nominato(dataset):
    indice, _ = _indice(dataset)
    _, doc, atteso = next(x for x in dataset if x[2].tipo.value == "etf" and x[0]["impaginazione"] == "tabellare")
    passaggi = indice.cerca(f"Qual è il periodo di detenzione raccomandato del {atteso.nome_prodotto}?", 3)
    assert passaggi[0].documento == doc.codice
    assert "detenzione raccomandato" in passaggi[0].testo.lower()


def test_sezioni_divise_alle_domande():
    pezzi = rag._sezioni("Quali sono i costi?\nCosti di ingresso 1%\nPer quanto tempo devo detenerlo?\n5 anni", 10, 3)
    assert pezzi == ["Quali sono i costi?\nCosti di ingresso 1%", "Per quanto tempo devo detenerlo?\n5 anni"]


def test_senza_chiave_risposta_estrattiva(dataset):
    indice, _ = _indice(dataset)
    r = rag.rispondi(indice, "costi di uscita", client=None)
    assert not r.generata and r.fonti and all(f.pagina >= 1 for f in r.fonti)


def test_citazioni_mappate_alla_pagina(dataset, api_finta):
    indice, _ = _indice(dataset)
    _, doc, atteso = dataset[6]
    domanda = f"Quali sono i costi di ingresso del {atteso.nome_prodotto}?"
    attesi = indice.cerca(domanda)
    api = api_finta([{"content": [
        {"type": "text", "text": "I costi di ingresso sono indicati nel KID", "citations": [
            {"type": "char_location", "cited_text": attesi[0].testo[:40], "document_index": 0,
             "document_title": "x", "start_char_index": 0, "end_char_index": 40}]},
        {"type": "text", "text": "."}]}])
    registro = Registro()
    r = rag.rispondi(indice, domanda, api.client(), registro)
    assert r.testo == "I costi di ingresso sono indicati nel KID [1]."
    assert (r.fonti[0].documento, r.fonti[0].pagina) == (attesi[0].documento, attesi[0].pagina)
    corpo = api.messaggi[0]
    documenti = [b for b in corpo["messages"][0]["content"] if b["type"] == "document"]
    assert all(b["citations"] == {"enabled": True} for b in documenti)
    assert registro.chiamate == 1 and r.costo_usd > 0


def test_riepilogo_come_fonte(dataset, api_finta):
    indice, docs = _indice(dataset)
    tabella = rag.riepilogo({d.codice: er.estrai(d) for d in docs})
    api = api_finta([{"content": [{"type": "text", "text": "L'ETF più economico è …", "citations": [
        {"type": "char_location", "cited_text": "riga", "document_index": 0, "document_title": "Dati estratti dai KID",
         "start_char_index": 0, "end_char_index": 4}]}]}])
    r = rag.rispondi(indice, "Quale ETF ha l'incidenza dei costi più bassa?", api.client(), tabella=tabella)
    assert r.fonti[0].documento == "riepilogo" and r.fonti[0].pagina == 0
    primo = api.messaggi[0]["messages"][0]["content"][0]
    assert primo["title"] == "Dati estratti dai KID" and "Incidenza annua costi" in primo["source"]["data"]
