"""Misura dell'accuratezza di estrazione sul dataset con valori di riferimento.

Ogni KID ha 16 campi. Un campo è corretto se coincide con il valore atteso: testo uguale a meno di maiuscole, spazi
e trattini; numeri entro la tolleranza (0,01 punti per percentuali, 0,05 anni per il periodo). Un valore mancante
quando è atteso conta come errore. Per ogni estrattore si riportano l'accuratezza per campo, per impaginazione e
per documento (tutti i 16 campi corretti), con costo e tempo delle chiamate.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .pdf import Documento, leggi_pdf
from .schema import CAMPI, DatiKid, valore

TOLLERANZA_PCT = 0.0101
TOLLERANZA_ANNI = 0.05


def _norm(testo: str) -> str:
    t = unicodedata.normalize("NFKC", testo).casefold()
    t = re.sub(r"[–—‐-]", "-", t)
    return re.sub(r"\s+", " ", t).strip()


def corretto(campo: str, atteso, trovato) -> bool:
    if atteso is None or trovato is None:
        return atteso is None and (trovato is None or trovato == 0)
    if campo == "periodo_detenzione_anni":
        return abs(float(atteso) - float(trovato)) <= TOLLERANZA_ANNI
    if isinstance(atteso, float) or campo.endswith("_pct"):
        return abs(float(atteso) - float(trovato)) <= TOLLERANZA_PCT
    if isinstance(atteso, str) and isinstance(trovato, str):
        return _norm(atteso) == _norm(trovato)
    return atteso == trovato


@dataclass
class EsitoDocumento:
    codice: str
    impaginazione: str
    tipo: str
    campi_corretti: int
    errori: list[dict]
    costo_usd: float = 0.0
    secondi: float = 0.0
    errore: str | None = None


@dataclass
class Rapporto:
    estrattore: str
    documenti: list[EsitoDocumento] = field(default_factory=list)

    @property
    def accuratezza(self) -> float:
        totale = len(self.documenti) * len(CAMPI)
        return sum(d.campi_corretti for d in self.documenti) / totale if totale else 0.0

    @property
    def documenti_perfetti(self) -> float:
        return sum(d.campi_corretti == len(CAMPI) for d in self.documenti) / max(len(self.documenti), 1)

    def per_campo(self) -> dict[str, float]:
        errati = defaultdict(int)
        for d in self.documenti:
            for e in d.errori:
                errati[e["campo"]] += 1
        n = max(len(self.documenti), 1)
        return {c: 1 - errati[c] / n for c in CAMPI}

    def per_impaginazione(self) -> dict[str, float]:
        gruppi: dict[str, list[EsitoDocumento]] = defaultdict(list)
        for d in self.documenti:
            gruppi[d.impaginazione].append(d)
        return {k: sum(d.campi_corretti for d in v) / (len(v) * len(CAMPI)) for k, v in sorted(gruppi.items())}

    @property
    def costo_usd(self) -> float:
        return sum(d.costo_usd for d in self.documenti)

    @property
    def secondi(self) -> float:
        return sum(d.secondi for d in self.documenti)

    def sintesi(self) -> dict:
        return {"estrattore": self.estrattore, "documenti": len(self.documenti),
                "accuratezza_campi": round(self.accuratezza, 4),
                "documenti_perfetti": round(self.documenti_perfetti, 4),
                "per_impaginazione": {k: round(v, 4) for k, v in self.per_impaginazione().items()},
                "per_campo": {k: round(v, 4) for k, v in self.per_campo().items()},
                "costo_usd": round(self.costo_usd, 4),
                "costo_medio_usd": round(self.costo_usd / max(len(self.documenti), 1), 5),
                "secondi_medi": round(self.secondi / max(len(self.documenti), 1), 2)}

    def salva(self, percorso: Path) -> None:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(json.dumps({"sintesi": self.sintesi(), "documenti": [asdict(d) for d in self.documenti]},
                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def confronta(atteso: DatiKid, trovato: DatiKid) -> list[dict]:
    errori = []
    for c in CAMPI:
        a, t = valore(atteso, c), valore(trovato, c)
        if not corretto(c, a, t):
            errori.append({"campo": c, "atteso": getattr(a, "value", a), "trovato": getattr(t, "value", t)})
    return errori


def carica_dataset(cartella: Path) -> list[tuple[dict, Documento, DatiKid]]:
    indice = json.loads((cartella / "indice.json").read_text(encoding="utf-8"))
    out = []
    for voce in indice:
        doc = leggi_pdf(cartella / "kid" / f"{voce['codice']}.pdf")
        atteso = DatiKid.model_validate_json((cartella / "attesi" / f"{voce['codice']}.json").read_text("utf-8"))
        out.append((voce, doc, atteso))
    return out


Estrattore = Callable[[Documento], tuple[DatiKid, float]]  # dati estratti e costo in dollari


def valuta(nome: str, estrattore: Estrattore, dataset: list[tuple[dict, Documento, DatiKid]],
           su_errore: Callable[[str, Exception], None] | None = None) -> Rapporto:
    rapporto = Rapporto(nome)
    for voce, doc, atteso in dataset:
        inizio = time.perf_counter()
        try:
            trovato, costo = estrattore(doc)
            errori, msg = confronta(atteso, trovato), None
        except Exception as e:  # un documento fallito conta come tutti i campi errati, la valutazione continua
            if su_errore:
                su_errore(voce["codice"], e)
            trovato, costo, msg = None, 0.0, f"{type(e).__name__}: {e}"
            errori = [{"campo": c, "atteso": None, "trovato": None} for c in CAMPI]
        rapporto.documenti.append(EsitoDocumento(
            voce["codice"], voce["impaginazione"], voce["tipo"], len(CAMPI) - len(errori), errori,
            round(costo, 6), round(time.perf_counter() - inizio, 3), msg))
    return rapporto


def tabella_markdown(rapporti: list[Rapporto]) -> str:
    impaginazioni = sorted({k for r in rapporti for k in r.per_impaginazione()})
    righe = ["| Estrattore | Campi corretti | KID senza errori | " + " | ".join(impaginazioni) +
             " | Costo per KID | Tempo per KID |",
             "|---|---:|---:|" + "---:|" * len(impaginazioni) + "---:|---:|"]
    for r in rapporti:
        s = r.sintesi()
        righe.append(f"| {r.estrattore} | {s['accuratezza_campi']:.1%} | {s['documenti_perfetti']:.1%} | " +
                     " | ".join(f"{s['per_impaginazione'].get(k, 0):.1%}" for k in impaginazioni) +
                     f" | ${s['costo_medio_usd']:.4f} | {s['secondi_medi']:.1f} s |")
    return "\n".join(righe)
