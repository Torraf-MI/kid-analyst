"""Generatore di KID PRIIPs sintetici con i valori di riferimento noti per costruzione.

I documenti seguono lo schema del Regolamento delegato 2017/653 (Prodotto, Cos'è, Rischi e scenari, Insolvenza,
Costi, Periodo di detenzione, Reclami) ma con tre impaginazioni diverse, come capita leggendo KID di case diverse:

* ``tabellare``: tabelle standard, SRI scritto nel testo, periodo in anni;
* ``discorsivo``: costi descritti in prosa, scenari in ordine inverso, sezioni spostate fra le pagine;
* ``grafico``: SRI indicato solo dalla casella evidenziata della scala, periodo in mesi, scenari trasposti,
  "Nessuno" al posto dello zero.

Società e prodotti sono inventati. I valori sono coerenti fra loro: l'incidenza annuale dei costi deriva dalle
singole voci e il rendimento dello scenario moderato al lordo dei costi è quello al netto più l'incidenza.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .schema import Costi, DatiKid, Scenari, TipoProdotto

IMPAGINAZIONI = ["tabellare", "discorsivo", "grafico"]
DATA_DOCUMENTO = date(2026, 11, 2)
INVESTIMENTO = 10_000

CASE_FONDI = ["Meridiana Investimenti SGR S.p.A.", "Aurora Asset Management S.A.", "Lagunare Gestioni SGR S.p.A."]
CASE_ETF = ["Polaris Index Funds plc", "Aurora ETF ICAV"]
EMITTENTI = ["Borealis Bank AG", "Banca Levante S.p.A."]
STRATEGIE_FONDI = [
    ("Monetario Euro", 1), ("Obbligazionario Euro Breve Termine", 2), ("Obbligazionario Globale Aggregate", 3),
    ("Bilanciato Prudente", 3), ("Flessibile Multi Asset", 4), ("Azionario Europa", 5),
    ("Azionario Globale Sostenibile", 5), ("Azionario Paesi Emergenti", 6), ("Azionario Tecnologia", 6),
]
INDICI_ETF = [
    ("Euro Government Bond 1-3", 2), ("Euro Corporate Bond", 3), ("Global Aggregate Bond EUR Hedged", 3),
    ("MSCI World", 4), ("S&P 500", 5), ("MSCI Europe Small Cap", 5), ("MSCI Emerging Markets", 5),
]
CERTIFICATI = [
    ("Cash Collect Memory", "Euro Stoxx 50", 4), ("Bonus Cap", "FTSE MIB", 5),
    ("Phoenix Memory Worst Of", "Enel, Eni, Intesa Sanpaolo", 6), ("Equity Protection 95%", "Euro Stoxx 50", 3),
    ("Cash Collect Autocallable", "Stellantis", 6),
]
NOME_CLASSE_SRI = {1: "più bassa", 2: "bassa", 3: "medio-bassa", 4: "media", 5: "medio-alta", 6: "seconda più alta",
                   7: "più alta"}


@dataclass
class Kid:
    codice: str
    impaginazione: str
    dati: DatiKid
    rendimenti_1_anno: dict[str, float]
    data_scadenza: date | None = None


# --- valori -------------------------------------------------------------------------------------------------

def isin(paese: str, rng: random.Random) -> str:
    """ISIN con cifra di controllo valida (algoritmo di Luhn sulle cifre ottenute convertendo le lettere)."""
    corpo = paese + "".join(rng.choice("0123456789") for _ in range(9))
    cifre = "".join(str(int(c, 36)) for c in corpo)
    somma = 0
    for i, c in enumerate(reversed(cifre)):
        n = int(c) * (2 if i % 2 == 0 else 1)
        somma += n // 10 + n % 10
    return corpo + str((10 - somma % 10) % 10)


def _r(x: float, d: int = 2) -> float:
    return round(x + 0.0, d)


def _scenari(sri: int, incidenza: float, rng: random.Random) -> tuple[Scenari, dict[str, float]]:
    lordo = [1.6, 2.6, 3.6, 4.8, 5.9, 7.2, 8.5][sri - 1] + rng.uniform(-0.6, 0.6)
    moderato = lordo - incidenza
    ampiezza = 0.9 + sri * 1.15 + rng.uniform(-0.4, 0.4)
    s = Scenari(stress_pct=_r(moderato - 2.6 * ampiezza), sfavorevole_pct=_r(moderato - ampiezza),
                moderato_pct=_r(moderato), favorevole_pct=_r(moderato + 1.1 * ampiezza))
    un_anno = {"stress": _r(-6 - 7.5 * sri + rng.uniform(-3, 3)),
               "sfavorevole": _r(-2 - 3.2 * sri + rng.uniform(-2, 2)),
               "moderato": _r(moderato + rng.uniform(-1, 1)), "favorevole": _r(3 + 4.1 * sri + rng.uniform(-2, 2))}
    return s, un_anno


def crea_prodotti(n: int = 30, seme: int = 2026) -> list[Kid]:
    rng = random.Random(seme)
    tipi = [TipoProdotto.fondo, TipoProdotto.etf, TipoProdotto.certificato]
    kid: list[Kid] = []
    for i in range(n):
        impaginazione = IMPAGINAZIONI[i % 3]
        tipo = tipi[(i // 3) % 3] if i % 4 else rng.choice(tipi)
        scadenza = None
        if tipo is TipoProdotto.fondo:
            strategia, sri = rng.choice(STRATEGIE_FONDI)
            casa = rng.choice(CASE_FONDI)
            nome = f"{casa.split()[0]} {strategia} – Classe {rng.choice(['A', 'R', 'C'])}"
            rhp = min(7, max(2, sri + rng.choice([0, 1, 2])))
            costi = Costi(ingresso_pct=rng.choice([0.0, 1.0, 1.5, 2.0, 2.5, 3.0]), uscita_pct=0.0,
                          gestione_pct=_r(rng.uniform(0.45, 0.35 + 0.3 * sri)),
                          transazione_pct=_r(rng.uniform(0.03, 0.08 * sri)),
                          performance_pct=rng.choice([0.0, 0.0, 0.0, _r(rng.uniform(0.05, 0.35))]))
            paese, ideatore = ("IT" if "SGR" in casa else "LU"), casa
        elif tipo is TipoProdotto.etf:
            indice, sri = rng.choice(INDICI_ETF)
            ideatore = rng.choice(CASE_ETF)
            nome = f"{ideatore.split()[0]} {indice} UCITS ETF ({rng.choice(['Acc', 'Dist'])})"
            rhp = 3 if sri <= 2 else rng.choice([5, 6, 7])
            costi = Costi(ingresso_pct=0.0, uscita_pct=0.0, gestione_pct=_r(rng.uniform(0.05, 0.45)),
                          transazione_pct=_r(rng.uniform(0.0, 0.09)), performance_pct=0.0)
            paese = "IE"
        else:
            struttura, sottostante, sri = rng.choice(CERTIFICATI)
            ideatore = rng.choice(EMITTENTI)
            rhp = rng.choice([2, 3, 4, 5])
            scadenza = DATA_DOCUMENTO.replace(year=DATA_DOCUMENTO.year + rhp, day=rng.choice([6, 13, 20]))
            nome = f"{struttura} su {sottostante} – scadenza {scadenza:%d/%m/%Y}"
            costi = Costi(ingresso_pct=_r(rng.uniform(0.9, 3.6)), uscita_pct=rng.choice([0.0, 0.25, 0.5]),
                          gestione_pct=0.0, transazione_pct=0.0, performance_pct=0.0)
            paese = "DE" if "AG" in ideatore else "IT"
        correnti = costi.gestione_pct + costi.transazione_pct + costi.performance_pct
        costi.incidenza_annua_pct = _r(correnti + (costi.ingresso_pct + costi.uscita_pct) / rhp)
        scenari, un_anno = _scenari(sri, costi.incidenza_annua_pct, rng)
        dati = DatiKid(nome_prodotto=nome, isin=isin(paese, rng), ideatore=ideatore, tipo=tipo, sri=sri,
                       periodo_detenzione_anni=float(rhp), costi=costi, scenari=scenari)
        kid.append(Kid(f"kid_{i + 1:02d}", impaginazione, dati, un_anno, scadenza))
    return kid


# --- formattazione ------------------------------------------------------------------------------------------

def pct(x: float, spazio: bool = False) -> str:
    return f"{x:.2f}".replace(".", ",") + (" %" if spazio else "%")


def eur(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".") + " EUR"


def _art(x: float) -> str:
    """Preposizione articolata davanti alla percentuale: "all'1,45%", "allo 0,12%", "al 2,10%"."""
    testo = pct(x)
    if testo.startswith(("1,", "11", "8")):
        return "all'" + testo
    if testo.startswith("0,"):
        return "allo " + testo
    return "al " + testo


STILI = getSampleStyleSheet()
TITOLO = ParagraphStyle("titolo", parent=STILI["Title"], fontSize=15, spaceAfter=4)
SEZIONE = ParagraphStyle("sezione", parent=STILI["Heading2"], fontSize=11.5, spaceBefore=8, spaceAfter=3,
                         textColor=colors.HexColor("#1f4e8c"))
TESTO = ParagraphStyle("testo", parent=STILI["BodyText"], fontSize=8.6, leading=11)
PICCOLO = ParagraphStyle("piccolo", parent=TESTO, fontSize=7.4, leading=9.2, textColor=colors.HexColor("#444444"))
CELLA = ParagraphStyle("cella", parent=TESTO, fontSize=8, leading=10)
CENTRO = ParagraphStyle("centro", parent=CELLA, alignment=TA_CENTER)

STILE_TABELLA = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa4b6")),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eff9")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
])


def _p(testo: str, stile: ParagraphStyle = TESTO) -> Paragraph:
    return Paragraph(testo.replace("&", "&amp;"), stile)  # "S&P 500": la & è un carattere, non un'entità


def _tabella(righe: list[list], larghezze: list[float], stile: TableStyle = STILE_TABELLA) -> Table:
    celle = [[_p(c, CELLA) if isinstance(c, str) else c for c in r] for r in righe]
    t = Table(celle, colWidths=[w * mm for w in larghezze])
    t.setStyle(stile)
    return t


def _descrizione(k: Kid) -> str:
    d = k.dati
    if d.tipo is TipoProdotto.certificato:
        return (f"Tipo: certificato di investimento ({k.dati.nome_prodotto.split(' su ')[0]}), strumento finanziario "
                f"derivato cartolarizzato emesso da {d.ideatore}. Termine: il prodotto scade il "
                f"{k.data_scadenza:%d/%m/%Y}; può essere rimborsato anticipatamente se il sottostante, alle date di "
                "osservazione, è pari o superiore al livello iniziale. Obiettivi: pagare premi periodici condizionati "
                "e, a scadenza, restituire il capitale se il sottostante non è sceso sotto la barriera. Se il "
                "sottostante è sotto la barriera, il rimborso è ridotto in proporzione alla sua performance.")
    if d.tipo is TipoProdotto.etf:
        return ("Tipo: quote di un fondo indicizzato quotato (UCITS ETF) negoziate in borsa. Obiettivi: replicare "
                "l'andamento dell'indice di riferimento al lordo delle commissioni, mediante replica fisica "
                "ottimizzata. Le quote possono essere acquistate e vendute ogni giorno di borsa aperta. "
                "Termine: il fondo non ha scadenza.")
    return ("Tipo: fondo comune di investimento armonizzato (OICVM). Obiettivi: accrescere il valore del capitale "
            "investito nel periodo di detenzione raccomandato, investendo secondo la politica descritta nel "
            "prospetto. Il fondo è a gestione attiva. Il rimborso delle quote può essere richiesto in ogni "
            "giorno lavorativo. Termine: il fondo non ha scadenza.")


def _investitore(k: Kid, rhp_testo: str) -> str:
    esperienza = "con conoscenza ed esperienza di prodotti strutturati" if k.dati.tipo is TipoProdotto.certificato \
        else "anche senza particolare esperienza dei mercati finanziari"
    return (f"Investitori al dettaglio a cui si intende commercializzare il prodotto: clienti {esperienza}, con un "
            f"orizzonte di investimento di almeno {rhp_testo} e in grado di sopportare perdite di capitale.")


def _costi_totali(k: Kid) -> tuple[float, float, float]:
    c, rhp = k.dati.costi, int(k.dati.periodo_detenzione_anni)
    correnti = c.gestione_pct + c.transazione_pct + c.performance_pct
    inc_1 = _r(c.ingresso_pct + c.uscita_pct + correnti)
    tot_1 = INVESTIMENTO * inc_1 / 100
    tot_rhp = INVESTIMENTO * c.incidenza_annua_pct / 100 * rhp * (1 + 0.02 * rhp)
    return inc_1, tot_1, tot_rhp


def _voci_costo(k: Kid, zero_testo: str | None = None, spazio: bool = False) -> list[list[str]]:
    c = k.dati.costi

    def v(x: float) -> str:
        return zero_testo if (zero_testo and x == 0) else pct(x, spazio)

    return [
        ["Costi di ingresso", f"{v(c.ingresso_pct)} dell'importo pagato al momento della sottoscrizione. Questo è "
                              "l'importo massimo che vi sarà addebitato; la persona che vi vende il prodotto vi "
                              "informerà del costo effettivo.", eur(INVESTIMENTO * c.ingresso_pct / 100)],
        ["Costi di uscita", (f"{v(c.uscita_pct)} del vostro investimento prima che vi venga pagato."
                             if c.uscita_pct else f"{v(0.0)}. Non addebitiamo costi di uscita per questo prodotto."),
         eur(INVESTIMENTO * c.uscita_pct / 100)],
        ["Commissioni di gestione e altri costi amministrativi o di esercizio",
         f"{v(c.gestione_pct)} del valore dell'investimento all'anno. Si tratta di una stima basata sui costi "
         "effettivi dell'ultimo anno.", eur(INVESTIMENTO * c.gestione_pct / 100)],
        ["Costi di transazione", f"{v(c.transazione_pct)} del valore dell'investimento all'anno. Si tratta di una "
                                 "stima dei costi sostenuti per l'acquisto e la vendita degli investimenti "
                                 "sottostanti.",
         eur(INVESTIMENTO * c.transazione_pct / 100)],
        ["Commissioni di performance",
         (f"{v(c.performance_pct)}: 20% della sovraperformance rispetto al parametro di riferimento, calcolata come "
          "media degli ultimi cinque anni." if c.performance_pct else
          f"{v(0.0)}. Per questo prodotto non si applicano commissioni di performance."),
         eur(INVESTIMENTO * c.performance_pct / 100)],
    ]


def _rimborso(r: float, anni: int) -> float:
    return INVESTIMENTO * (1 + r / 100) ** anni


NOMI_SCENARI = [("stress", "Stress"), ("sfavorevole", "Sfavorevole"), ("moderato", "Moderato"),
                ("favorevole", "Favorevole")]


def _righe_scenari(k: Kid, ordine: list[tuple[str, str]]) -> list[list[str]]:
    rhp = int(k.dati.periodo_detenzione_anni)
    righe = []
    for chiave, nome in ordine:
        r_rhp = getattr(k.dati.scenari, f"{chiave}_pct")
        r_1 = k.rendimenti_1_anno[chiave]
        righe.append([f"<b>{nome}</b>", "Possibile rimborso al netto dei costi", eur(_rimborso(r_1, 1)),
                      eur(_rimborso(r_rhp, rhp))])
        righe.append(["", "Rendimento medio per ciascun anno", pct(r_1), pct(r_rhp)])
    return righe


def _nota_scenari() -> Paragraph:
    return _p("Gli scenari sfavorevole, moderato e favorevole illustrati rappresentano esempi che utilizzano la "
              "performance peggiore, media e migliore del prodotto o di un indice di riferimento idoneo negli ultimi "
              "10 anni. I mercati potrebbero evolvere in modo molto diverso in futuro. Lo scenario di stress mostra "
              "che cosa potreste ottenere in circostanze di mercato estreme. Le cifre riportate comprendono tutti i "
              "costi del prodotto in quanto tale, ma non tengono conto della vostra situazione fiscale personale.",
              PICCOLO)


def _insolvenza(k: Kid) -> list:
    if k.dati.tipo is TipoProdotto.certificato:
        testo = (f"Siete esposti al rischio che {k.dati.ideatore} non sia in grado di adempiere ai propri obblighi. "
                 "Il prodotto non è coperto da alcun sistema di indennizzo o garanzia degli investitori. In caso di "
                 "risoluzione dell'emittente, le autorità possono applicare il bail-in e ridurre o convertire il "
                 "credito dell'investitore.")
    else:
        testo = ("Le attività del fondo sono custodite presso il depositario e sono separate da quelle della società "
                 "di gestione. In caso di insolvenza della società di gestione, il patrimonio del fondo non sarà "
                 "utilizzato per soddisfare i suoi creditori. Non esiste un sistema di indennizzo degli investitori.")
    return [_p(f"Cosa accade se {k.dati.ideatore} non è in grado di corrispondere quanto dovuto?", SEZIONE), _p(testo)]


def _reclami(k: Kid) -> list:
    return [_p("Come presentare reclami?", SEZIONE),
            _p(f"Eventuali reclami possono essere presentati per iscritto a {k.dati.ideatore}, Ufficio Reclami, "
               "anche via posta elettronica certificata. In caso di risposta insoddisfacente è possibile rivolgersi "
               "all'Arbitro per le Controversie Finanziarie (ACF)."),
            _p("Altre informazioni pertinenti", SEZIONE),
            _p("Il prospetto, l'ultima relazione annuale e le performance passate degli ultimi 10 anni sono "
               "disponibili gratuitamente sul sito internet dell'ideatore. Documento redatto a scopo dimostrativo: "
               "società, prodotti e valori sono simulati.", PICCOLO)]


def _rischio_testo(k: Kid, frase_sri: str) -> list:
    extra = (" Questo prodotto non comprende alcuna protezione dalla performance futura del mercato; pertanto "
             "potreste perdere il vostro intero investimento o parte di esso.")
    if k.dati.tipo is TipoProdotto.certificato:
        extra += " Il rimborso dipende anche dalla capacità di pagamento dell'emittente."
    return [_p(frase_sri + extra)]


# --- impaginazioni ------------------------------------------------------------------------------------------

def _intestazione(k: Kid) -> list:
    return [_p("Documento contenente le informazioni chiave", TITOLO),
            _p("<b>Scopo</b>: il presente documento fornisce le informazioni chiave relative a questo prodotto "
               "d'investimento. Non si tratta di un documento promozionale. Le informazioni, prescritte per legge, "
               "hanno lo scopo di aiutarvi a capire le caratteristiche, i rischi, i costi, i guadagni e le perdite "
               "potenziali di questo prodotto e di aiutarvi a fare un raffronto con altri prodotti d'investimento.",
               PICCOLO)]


def _tabellare(k: Kid) -> list:
    d, rhp = k.dati, int(k.dati.periodo_detenzione_anni)
    inc_1, tot_1, tot_rhp = _costi_totali(k)
    lordo = d.scenari.moderato_pct + d.costi.incidenza_annua_pct
    return [
        *_intestazione(k),
        _p("Prodotto", SEZIONE),
        _p(f"<b>Nome del prodotto:</b> {d.nome_prodotto}<br/><b>Codice ISIN:</b> {d.isin}<br/>"
           f"<b>Ideatore:</b> {d.ideatore}<br/><b>Autorità competente:</b> Consob<br/>"
           f"<b>Data di realizzazione del documento:</b> {DATA_DOCUMENTO:%d/%m/%Y}"),
        _p("Cos'è questo prodotto?", SEZIONE), _p(_descrizione(k)), _p(_investitore(k, f"{rhp} anni")),
        PageBreak(),
        _p("Quali sono i rischi e qual è il potenziale rendimento?", SEZIONE),
        *_rischio_testo(k, f"L'indicatore di rischio presuppone che il prodotto sia mantenuto per {rhp} anni. "
                           f"Abbiamo classificato questo prodotto al livello {d.sri} su 7, che corrisponde alla "
                           f"classe di rischio {NOME_CLASSE_SRI[d.sri]}."),
        Spacer(1, 4),
        _p(f"<b>Periodo di detenzione raccomandato:</b> {rhp} anni<br/><b>Esempio di investimento:</b> "
           f"{eur(INVESTIMENTO)}"),
        _tabella([["Scenari", "", "In caso di uscita dopo 1 anno", f"In caso di uscita dopo {rhp} anni"],
                  ["<b>Minimo</b>", "Non esiste un rendimento minimo garantito. Potreste perdere il vostro intero "
                                    "investimento o parte di esso.", "", ""],
                  *_righe_scenari(k, NOMI_SCENARI)], [24, 62, 40, 40]),
        _nota_scenari(),
        PageBreak(),
        *_insolvenza(k),
        _p("Quali sono i costi?", SEZIONE),
        _p("<b>Andamento dei costi nel tempo.</b> Le tabelle mostrano gli importi prelevati dal vostro "
           f"investimento per coprire i diversi tipi di costi, ipotizzando un investimento di {eur(INVESTIMENTO)}."),
        _tabella([["", "In caso di uscita dopo 1 anno", f"In caso di uscita dopo {rhp} anni"],
                  ["Costi totali", eur(tot_1), eur(tot_rhp)],
                  ["Incidenza annuale dei costi (*)", pct(inc_1), pct(d.costi.incidenza_annua_pct)]], [60, 50, 50]),
        _p(f"(*) Dimostra in che misura i costi riducono il rendimento ogni anno durante il periodo di detenzione. "
           f"Se l'uscita avviene al termine del periodo di detenzione raccomandato, si prevede che il rendimento "
           f"medio annuo sarà pari al {pct(lordo)} prima dei costi e al {pct(d.scenari.moderato_pct)} al netto dei "
           "costi.", PICCOLO),
        Spacer(1, 4), _p("<b>Composizione dei costi</b>"),
        _tabella([["Costi una tantum di ingresso o di uscita", "", "Incidenza in caso di uscita dopo 1 anno"],
                  *_voci_costo(k)], [40, 90, 36]),
        _p("Per quanto tempo devo detenerlo e posso ritirare il capitale prematuramente?", SEZIONE),
        _p(f"<b>Periodo di detenzione raccomandato: {rhp} anni.</b> Il periodo è stato scelto in base al profilo "
           "di rischio e rendimento del prodotto. Potete disinvestire prima, ma il rendimento potrebbe essere "
           "inferiore."),
        *_reclami(k),
    ]


def _discorsivo(k: Kid) -> list:
    d, rhp = k.dati, int(k.dati.periodo_detenzione_anni)
    c = d.costi
    inc_1, tot_1, tot_rhp = _costi_totali(k)
    ingresso = f"costi di ingresso pari {_art(c.ingresso_pct)} dell'importo investito" if c.ingresso_pct \
        else "nessun costo di ingresso"
    uscita = f"costi di uscita pari {_art(c.uscita_pct)} dell'importo rimborsato" if c.uscita_pct \
        else "nessun costo di uscita"
    performance = (f"commissioni di performance stimate {_art(c.performance_pct)} annuo" if c.performance_pct
                   else "nessuna commissione di performance")
    return [
        *_intestazione(k),
        _p(f"<b>{d.nome_prodotto}</b>", ParagraphStyle("nome", parent=TESTO, fontSize=12, leading=15)),
        _p(f"ISIN: {d.isin}. Il prodotto è realizzato da {d.ideatore}, soggetto alla vigilanza della Consob. "
           f"Documento aggiornato al {DATA_DOCUMENTO:%d/%m/%Y}."),
        _p("Cos'è questo prodotto?", SEZIONE), _p(_descrizione(k)), _p(_investitore(k, f"{rhp} anni")),
        _p("Quali sono i rischi e qual è il potenziale rendimento?", SEZIONE),
        *_rischio_testo(k, f"L'indicatore sintetico di rischio (SRI) di questo prodotto è pari a {d.sri} su una "
                           "scala da 1 a 7. Esso indica la probabilità che il prodotto subisca perdite a causa di "
                           "movimenti sul mercato o dell'incapacità di pagarvi."),
        PageBreak(),
        _p("Scenari di performance", SEZIONE),
        _p(f"Importi in caso di investimento di {eur(INVESTIMENTO)}. Il periodo di detenzione raccomandato è di "
           f"{rhp} anni."),
        _tabella([["Scenari", "", "Dopo 1 anno", f"Dopo {rhp} anni (periodo raccomandato)"],
                  *_righe_scenari(k, list(reversed(NOMI_SCENARI)))], [24, 62, 36, 44]),
        _p("Non esiste un rendimento minimo garantito.", PICCOLO), _nota_scenari(),
        *_insolvenza(k),
        PageBreak(),
        _p("Quali sono i costi?", SEZIONE),
        _p(f"Sono previsti {ingresso} e {uscita}. Ogni anno sono prelevati commissioni di gestione e altri costi "
           f"amministrativi o di esercizio pari {_art(c.gestione_pct)} del valore dell'investimento e costi di "
           f"transazione pari {_art(c.transazione_pct)}; sono inoltre previste {performance}."),
        _p(f"Su un investimento di {eur(INVESTIMENTO)}, i costi totali ammontano a {eur(tot_1)} in caso di uscita "
           f"dopo un anno ({pct(inc_1)} di incidenza) e a {eur(tot_rhp)} in caso di uscita al termine del periodo di "
           f"detenzione raccomandato. L'incidenza annuale dei costi in caso di uscita dopo {rhp} anni è pari "
           f"{_art(c.incidenza_annua_pct)}."),
        _p("Per quanto tempo devo detenerlo e posso ritirare il capitale prematuramente?", SEZIONE),
        _p(f"Periodo di detenzione raccomandato: {rhp} anni. Il disinvestimento anticipato è possibile in ogni "
           "giorno lavorativo, senza penali oltre ai costi di uscita indicati sopra."),
        *_reclami(k),
    ]


def _scala_sri(sri: int) -> Table:
    celle = [[_p(str(i), CENTRO) for i in range(1, 8)]]
    t = Table(celle, colWidths=[12 * mm] * 7, rowHeights=[8 * mm])
    stile = [("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#9aa4b6")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("BACKGROUND", (sri - 1, 0), (sri - 1, 0), colors.HexColor("#1f4e8c"))]
    t.setStyle(TableStyle(stile))
    t._cellvalues[0][sri - 1] = _p(f'<font color="white"><b>{sri}</b></font>', CENTRO)
    return t


def _grafico(k: Kid) -> list:
    d, rhp = k.dati, int(k.dati.periodo_detenzione_anni)
    mesi = rhp * 12
    inc_1, tot_1, tot_rhp = _costi_totali(k)
    colonne = [nome for _, nome in NOMI_SCENARI]

    def riga(funzione) -> list[str]:
        return [funzione(c) for c, _ in NOMI_SCENARI]

    rimborso_1 = riga(lambda c: eur(_rimborso(k.rendimenti_1_anno[c], 1)))
    rend_1 = riga(lambda c: pct(k.rendimenti_1_anno[c], True))
    rimborso_r = riga(lambda c: eur(_rimborso(getattr(d.scenari, f"{c}_pct"), rhp)))
    rend_r = riga(lambda c: pct(getattr(d.scenari, f"{c}_pct"), True))
    scadenza = f" (fino alla scadenza del {k.data_scadenza:%d/%m/%Y})" if k.data_scadenza else ""
    return [
        *_intestazione(k),
        _tabella([["Prodotto", d.nome_prodotto], ["Codice ISIN", d.isin], ["Ideatore del PRIIP", d.ideatore],
                  ["Vigilanza", "Consob"], ["Data del documento", f"{DATA_DOCUMENTO:%d.%m.%Y}"]], [40, 126],
                 TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa4b6")),
                             ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eff9"))])),
        _p("Cos'è questo prodotto?", SEZIONE), _p(_descrizione(k)), _p(_investitore(k, f"{mesi} mesi")),
        PageBreak(),
        _p("Quali sono i rischi e qual è il potenziale rendimento?", SEZIONE),
        _p("Indicatore di rischio — rischio più basso (1) … rischio più alto (7)", PICCOLO),
        _scala_sri(d.sri), Spacer(1, 3),
        *_rischio_testo(k, f"La classe evidenziata nella scala presuppone che il prodotto sia mantenuto per {mesi} "
                           "mesi. Il rischio effettivo può variare in misura significativa in caso di uscita "
                           "anticipata."),
        _p("Scenari di performance", SEZIONE),
        _p(f"Periodo di detenzione raccomandato: {mesi} mesi{scadenza}. Investimento: {eur(INVESTIMENTO)}."),
        _tabella([["", *colonne],
                  ["Uscita dopo 12 mesi: rimborso al netto dei costi", *rimborso_1],
                  ["Uscita dopo 12 mesi: rendimento medio annuo", *rend_1],
                  [f"Uscita dopo {mesi} mesi: rimborso al netto dei costi", *rimborso_r],
                  [f"Uscita dopo {mesi} mesi: rendimento medio annuo", *rend_r]], [58, 27, 27, 27, 27]),
        _nota_scenari(),
        PageBreak(),
        *_insolvenza(k),
        _p("Quali sono i costi?", SEZIONE),
        _tabella([["Investimento 10.000 EUR", "Uscita dopo 12 mesi", f"Uscita dopo {mesi} mesi"],
                  ["Costi totali", eur(tot_1), eur(tot_rhp)],
                  ["Incidenza annuale dei costi", pct(inc_1, True), pct(d.costi.incidenza_annua_pct, True)]],
                 [60, 50, 50]),
        Spacer(1, 4),
        _tabella([["Voce", "Descrizione", "Importo su 10.000 EUR"], *_voci_costo(k, "Nessuno", True)], [40, 90, 36]),
        _p("Per quanto tempo devo detenerlo e posso ritirare il capitale prematuramente?", SEZIONE),
        _p(f"Periodo di detenzione raccomandato: {mesi} mesi{scadenza}. Il prodotto può essere venduto sul mercato "
           "secondario; in condizioni di mercato eccezionali la vendita potrebbe non essere possibile o avvenire a "
           "un prezzo inferiore."),
        *_reclami(k),
    ]


IMPAGINATORI = {"tabellare": _tabellare, "discorsivo": _discorsivo, "grafico": _grafico}


def scrivi_pdf(k: Kid, percorso: Path) -> None:
    doc = SimpleDocTemplate(str(percorso), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"KID – {k.dati.nome_prodotto}", author=k.dati.ideatore,
                            invariant=1)

    def piede(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 9 * mm, f"{k.dati.ideatore} – KID {k.dati.isin}")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Pagina {documento.page} di 3")
        canvas.restoreState()

    doc.build(IMPAGINATORI[k.impaginazione](k), onFirstPage=piede, onLaterPages=piede)


def genera_dataset(cartella: Path, n: int = 30, seme: int = 2026) -> list[Kid]:
    (cartella / "kid").mkdir(parents=True, exist_ok=True)
    (cartella / "attesi").mkdir(parents=True, exist_ok=True)
    prodotti = crea_prodotti(n, seme)
    indice = []
    for k in prodotti:
        scrivi_pdf(k, cartella / "kid" / f"{k.codice}.pdf")
        (cartella / "attesi" / f"{k.codice}.json").write_text(
            json.dumps(k.dati.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        indice.append({"codice": k.codice, "impaginazione": k.impaginazione, "tipo": k.dati.tipo.value,
                       "nome": k.dati.nome_prodotto})
    (cartella / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return prodotti
