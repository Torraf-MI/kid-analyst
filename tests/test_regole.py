from kid_analyst import estrattore_regole as er
from kid_analyst.pdf import Documento, Pagina
from kid_analyst.valutazione import valuta


def test_layout_noti_perfetti_layout_nuovo_no(dataset):
    """Le regole sono scritte su "tabellare" e "discorsivo": lì sono esatte, sul layout mai visto no."""
    r = valuta("regole", lambda d: (er.estrai(d), 0.0), dataset).per_impaginazione()
    assert r["tabellare"] == 1.0 and r["discorsivo"] == 1.0
    assert r["grafico"] < 0.75


def test_prosa_e_nessun_costo():
    testo = ("Quali sono i costi?\nSono previsti costi di ingresso pari all'1,50% dell'importo investito e nessun "
             "costo di uscita. Ogni anno sono prelevati commissioni di gestione e altri costi amministrativi o di "
             "esercizio pari allo 0,88% del valore dell'investimento e costi di transazione pari allo 0,12%; "
             "sono inoltre previste nessuna commissione di performance. "
             "L'incidenza annuale dei costi in caso di uscita dopo 5 "
             "anni è pari al 1,30%.\nPeriodo di detenzione raccomandato: 60 mesi.")
    d = er.estrai(Documento("x", [Pagina(1, testo)], b""))
    c = d.costi
    assert (c.ingresso_pct, c.uscita_pct, c.gestione_pct, c.transazione_pct, c.performance_pct) == (
        1.5, 0.0, 0.88, 0.12, 0.0)
    assert c.incidenza_annua_pct == 1.30
    assert d.periodo_detenzione_anni == 5


def test_numeri_italiani():
    assert er.numero("1.234,56") == 1234.56
    assert er.numero("-2,50") == -2.5
