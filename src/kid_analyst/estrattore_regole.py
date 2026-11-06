"""Estrattore a regole: espressioni regolari scritte sulle impaginazioni "tabellare" e "discorsivo".

È il termine di paragone dell'estrattore con Claude. Le regole sono state sviluppate guardando solo quelle due
impaginazioni; la terza ("grafico") fa da layout mai visto, come succede quando arriva il KID di una nuova casa
prodotto. Non chiama servizi esterni e non costa nulla.
"""

from __future__ import annotations

import re

from .pdf import Documento
from .schema import Costi, DatiKid, Scenari, TipoProdotto

NUMERO = r"-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+|-?\d+"
PERCENTUALE = re.compile(rf"({NUMERO})\s*%")
ISIN = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")
SCENARI = {"stress": "stress", "sfavorevole": "sfavorevole", "moderato": "moderato", "favorevole": "favorevole"}
ZERO = re.compile(r"\b(nessun[oa]?|non addebitiamo|non si applicano|non previst[ei])\b", re.I)


def numero(testo: str) -> float:
    return float(testo.replace(".", "").replace(",", "."))


def _piatto(testo: str) -> str:
    return re.sub(r"\s+", " ", testo)


def _cerca(schemi: list[str], testo: str, flag: int = re.I | re.M) -> str | None:
    for s in schemi:
        m = re.search(s, testo, flag)
        if m:
            return m.group(1).strip()
    return None


def _nome(righe: list[str]) -> str | None:
    for r in righe:
        m = re.match(r"(?:Nome del prodotto:|Prodotto)\s+(.+)", r)
        if m:
            return m.group(1).strip()
    for i, r in enumerate(righe):  # impaginazione con il nome in evidenza sotto la sezione "Scopo"
        if r.rstrip().endswith("prodotti d'investimento.") and i + 1 < len(righe):
            return righe[i + 1].strip()
    return None


def _ideatore(testo: str) -> str | None:
    return _cerca([r"^Ideatore(?: del PRIIP)?:?\s+(.+)$", r"realizzato da (.+?), soggett", r"^(.+?) – KID "], testo)


def _tipo(testo: str, nome: str | None) -> TipoProdotto:
    if re.search(r"\bcertificat[oi]\b", testo, re.I):
        return TipoProdotto.certificato
    if (nome and "ETF" in nome) or "fondo indicizzato quotato" in testo:
        return TipoProdotto.etf
    return TipoProdotto.fondo


def _sri(piatto: str) -> int | None:
    v = _cerca([r"livello (\d) su 7", r"indicatore sintetico di rischio[^.]{0,40}? pari a (\d)",
                r"classe di rischio (\d)\b"], piatto)
    return int(v) if v else None


def _periodo(piatto: str) -> float | None:
    m = re.search(r"periodo di detenzione raccomandato(?: è di|:)?\s*(\d+)\s*(anni|anno|mesi)", piatto, re.I)
    if not m:
        return None
    n = float(m.group(1))
    return n / 12 if m.group(2).lower() == "mesi" else n


def _voce(piatto: str, etichette: list[str]) -> float | None:
    """Prima percentuale (o "nessuno") dopo l'etichetta, nella sezione dei costi."""
    for etichetta in etichette:
        for m in re.finditer(etichetta, piatto, re.I):
            finestra = piatto[m.end(): m.end() + 90]
            p, z = PERCENTUALE.search(finestra), ZERO.search(finestra)
            if z and (not p or z.start() < p.start()):
                return 0.0
            if p:
                return numero(p.group(1))
    return None


def _costi(piatto: str) -> Costi:
    i = piatto.lower().find("quali sono i costi")
    sezione = piatto[i:] if i >= 0 else piatto

    def zero_esplicito(voce: str) -> bool:
        return re.search(rf"nessun\w* (?:costo|commissione) di {voce}", sezione, re.I) is not None

    def voce(etichette: list[str], nome: str) -> float | None:
        return 0.0 if zero_esplicito(nome) else _voce(sezione, etichette)

    incidenza = None
    for m in re.finditer(r"incidenza annuale dei costi", sezione, re.I):
        trovate = PERCENTUALE.findall(sezione[m.end(): m.end() + 60])
        if trovate:
            incidenza = numero(trovate[-1])  # l'ultima colonna è il periodo di detenzione raccomandato
            break
    return Costi(
        ingresso_pct=voce([r"costi di ingresso"], "ingresso"),
        uscita_pct=voce([r"costi di uscita"], "uscita"),
        gestione_pct=_voce(sezione, [r"commissioni di gestione"]),
        transazione_pct=_voce(sezione, [r"costi di transazione"]),
        performance_pct=voce([r"commissioni di performance"], "performance"),
        incidenza_annua_pct=incidenza,
    )


def _scenari(righe: list[str]) -> Scenari:
    valori: dict[str, float] = {}
    corrente = None
    for r in righe:
        prima = r.split(" ", 1)[0].lower()
        if prima in SCENARI and "rimborso" in r.lower():
            corrente = SCENARI[prima]
        elif corrente and r.lower().startswith("rendimento medio per ciascun anno"):
            trovate = PERCENTUALE.findall(r)
            if trovate:
                valori[f"{corrente}_pct"] = numero(trovate[-1])
            corrente = None
    return Scenari(**valori)


def estrai(doc: Documento) -> DatiKid:
    testo = doc.testo
    righe = [r for r in testo.splitlines() if r.strip()]
    piatto = _piatto(testo)
    nome = _nome(righe)
    m = ISIN.search(testo)
    return DatiKid(
        nome_prodotto=nome or "", isin=m.group(1) if m else None, ideatore=_ideatore(testo),
        tipo=_tipo(piatto, nome), sri=_sri(piatto), periodo_detenzione_anni=_periodo(piatto),
        costi=_costi(piatto), scenari=_scenari(righe),
    )
