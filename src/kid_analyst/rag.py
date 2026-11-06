"""Domande in linguaggio naturale sui documenti caricati, con citazione della pagina.

1. Ogni pagina è divisa in passaggi di poche righe che si sovrappongono; ogni passaggio conserva documento e pagina.
2. BM25 (con una normalizzazione minima per l'italiano) sceglie i passaggi più pertinenti alla domanda.
3. Claude risponde usando solo quei passaggi, passati come documenti con le citazioni attive: ogni frase della
   risposta porta con sé il testo citato, da cui si risale al documento e alla pagina.

Senza chiave API la risposta è estrattiva: i passaggi più pertinenti con il loro riferimento.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from .costi_api import Registro
from .pdf import Documento

MODELLO_RISPOSTE = "claude-opus-5-5"
MAX_TOKEN = 6000

STOPWORD = set("""a ad al alla alle allo agli ai all che chi cui con da dal dalla dalle dai degli dei del della delle
dello di e ed gli i il in la le lo nei nel nella nelle nello o per qual quale quali quanto se si su sul sulla sono un
una uno questo questa questi queste quello quella ha hanno è non come più cosa dopo prima tra fra vi ci anche mio
mia suo sua loro""".split())

ISTRUZIONI = """Rispondi in italiano alle domande sui documenti finanziari forniti (KID e simili).
Usa solo le informazioni dei documenti: se la risposta non c'è, dillo. Riporta i numeri come sono scritti,
precisando a quale prodotto si riferiscono. Rispondi in modo breve e diretto, senza dare consigli di investimento."""


def _token(testo: str) -> list[str]:
    t = unicodedata.normalize("NFKD", testo.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    parole = re.findall(r"[a-z]+|\d+(?:,\d+)?", t)
    # radice grossolana: costi/costo → cost, uscita/uscite → uscit
    return [p[:-1] if len(p) > 4 and p[-1] in "aeio" else p for p in parole if p not in STOPWORD]


@dataclass
class Passaggio:
    documento: str  # codice del documento
    titolo: str  # nome del prodotto
    pagina: int
    testo: str


@dataclass
class Fonte:
    documento: str
    titolo: str
    pagina: int
    citazione: str


@dataclass
class Risposta:
    testo: str
    fonti: list[Fonte] = field(default_factory=list)
    passaggi: list[Passaggio] = field(default_factory=list)
    generata: bool = True  # False per la risposta estrattiva, senza modello
    costo_usd: float = 0.0


def _sezioni(testo: str, righe: int, sovrapposizione: int) -> list[str]:
    """Divide la pagina alle intestazioni del KID (le domande: "Quali sono i costi?") e poi in finestre di righe."""
    blocchi: list[list[str]] = [[]]
    for r in (r for r in testo.splitlines() if r.strip()):
        if r.rstrip().endswith("?") and len(r) < 120 and blocchi[-1]:
            blocchi.append([])
        blocchi[-1].append(r)
    out = []
    passo = max(righe - sovrapposizione, 1)
    for b in blocchi:
        for i in range(0, max(len(b) - sovrapposizione, 1), passo):
            out.append("\n".join(b[i:i + righe]))
    return [t for t in out if t]


class Indice:
    def __init__(self, documenti: list[Documento], titoli: dict[str, str] | None = None, righe: int = 10,
                 sovrapposizione: int = 3):
        titoli = titoli or {}
        self.passaggi: list[Passaggio] = []
        for doc in documenti:
            for pagina in doc.pagine:
                for testo in _sezioni(pagina.testo, righe, sovrapposizione):
                    self.passaggi.append(Passaggio(doc.codice, titoli.get(doc.codice, doc.codice), pagina.numero,
                                                   testo))
        self._bm25 = BM25Okapi([_token(p.testo) for p in self.passaggi]) if self.passaggi else None
        self._codici = list(dict.fromkeys(p.documento for p in self.passaggi))
        self._titolo = {c: titoli.get(c, c) for c in self._codici}
        self._titoli = BM25Okapi([_token(titoli.get(c, c)) for c in self._codici]) if self._codici else None

    def documenti_citati(self, domanda: str) -> set[str] | None:
        """Documenti il cui nome compare nella domanda ("...del Phoenix Memory?"); None se non ne nomina nessuno."""
        if not self._titoli or len(self._codici) < 2:
            return None
        punteggi = self._titoli.get_scores(_token(domanda))
        massimo = max(punteggi)
        if massimo <= 0:
            return None
        return {c for c, s in zip(self._codici, punteggi, strict=True) if s >= 0.6 * massimo}

    def cerca(self, domanda: str, k: int = 6) -> list[Passaggio]:
        """Passaggi più pertinenti, cercati solo nei documenti nominati nella domanda se ce ne sono."""
        if not self._bm25:
            return []
        ammessi = self.documenti_citati(domanda)
        parole = _token(domanda)
        if ammessi:  # il nome del prodotto ha già scelto i documenti: si cerca con il resto della domanda
            nei_titoli = {t for c in ammessi for t in _token(self._titolo[c])}
            parole = [t for t in parole if t not in nei_titoli] or parole
        punteggi = self._bm25.get_scores(parole)
        candidati = [i for i in range(len(self.passaggi)) if ammessi is None or self.passaggi[i].documento in ammessi]
        migliori = sorted(candidati, key=lambda i: punteggi[i], reverse=True)[:k]
        return [self.passaggi[i] for i in migliori if punteggi[i] > 0]


def _risposta_estrattiva(passaggi: list[Passaggio]) -> Risposta:
    if not passaggi:
        return Risposta("Nei documenti non ho trovato passaggi pertinenti alla domanda.", generata=False)
    fonti = [Fonte(p.documento, p.titolo, p.pagina, p.testo) for p in passaggi[:3]]
    return Risposta("Risposta generativa non disponibile (manca la chiave API): ecco i passaggi più pertinenti.",
                    fonti, passaggi, generata=False)


def riepilogo(prodotti: dict) -> str:
    """Tabella testuale dei dati estratti, utile alle domande che confrontano più prodotti."""
    righe = ["Prodotto | Tipo | SRI | Periodo raccomandato (anni) | Incidenza annua costi % | Ingresso % | Uscita % | "
             "Gestione % | Transazione % | Performance % | Scenario moderato % annuo"]
    for d in prodotti.values():
        c = d.costi
        righe.append(" | ".join(str(x) for x in [d.nome_prodotto, d.tipo.value, d.sri, d.periodo_detenzione_anni,
                                                  c.incidenza_annua_pct, c.ingresso_pct, c.uscita_pct, c.gestione_pct,
                                                  c.transazione_pct, c.performance_pct, d.scenari.moderato_pct]))
    return "\n".join(righe)


def rispondi(indice: Indice, domanda: str, client=None, registro: Registro | None = None, k: int = 6,
             modello: str = MODELLO_RISPOSTE, effort: str = "low", tabella: str | None = None) -> Risposta:
    """Risposta con citazioni. ``tabella`` (vedi ``riepilogo``) aggiunge i dati estratti come fonte, citata come
    pagina 0."""
    passaggi = indice.cerca(domanda, k)
    if client is None or not passaggi:
        return _risposta_estrattiva(passaggi)
    registro = registro or Registro()
    if tabella:
        passaggi = [Passaggio("riepilogo", "Dati estratti dai KID", 0, tabella), *passaggi]
    contenuto = [{"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": p.testo},
                  "title": f"{p.titolo} – pagina {p.pagina}" if p.pagina else p.titolo,
                  "citations": {"enabled": True}} for p in passaggi]
    contenuto.append({"type": "text", "text": domanda})
    messaggi = [{"role": "user", "content": contenuto}]
    conteggio = client.messages.count_tokens(model=modello, system=ISTRUZIONI, messages=messaggi)
    registro.autorizza(modello, conteggio.input_tokens, MAX_TOKEN)
    r = client.messages.create(model=modello, max_tokens=MAX_TOKEN, system=ISTRUZIONI, messages=messaggi,
                               output_config={"effort": effort})
    speso = registro.registra(modello, r.usage)
    if r.stop_reason == "refusal":
        return Risposta("La richiesta non può essere elaborata.", generata=True, costo_usd=speso)

    testo, fonti, visti = "", [], {}
    for blocco in r.content:
        if blocco.type != "text":
            continue
        testo += blocco.text
        rimandi = []
        for c in getattr(blocco, "citations", None) or []:
            p = passaggi[c.document_index]
            chiave = (p.documento, p.pagina, c.cited_text)
            if chiave not in visti:
                fonti.append(Fonte(p.documento, p.titolo, p.pagina, c.cited_text.strip()))
                visti[chiave] = len(fonti)
            if visti[chiave] not in rimandi:
                rimandi.append(visti[chiave])
        if rimandi:
            testo += "".join(f" [{n}]" for n in rimandi)
    return Risposta(testo.strip(), fonti, passaggi, True, speso)
