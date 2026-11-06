"""Dati strutturati di un KID PRIIPs (Regolamento UE 1286/2014 e Regolamento delegato 2017/653).

Lo stesso modello Pydantic serve a tre cose: è lo schema dell'output strutturato chiesto a Claude, il formato dei
valori di riferimento del dataset di valutazione e l'input del confronto fra prodotti. Le percentuali sono numeri
in punti percentuali (1,25% → 1.25), come le scrive il documento.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TipoProdotto(StrEnum):
    fondo = "fondo"
    etf = "etf"
    certificato = "certificato"


class Costi(BaseModel):
    ingresso_pct: float | None = Field(
        None, description="Costi di ingresso una tantum, % dell'importo investito. 0 se 'nessuno' o non applicati.")
    uscita_pct: float | None = Field(
        None, description="Costi di uscita una tantum, % dell'investimento. 0 se 'nessuno' o non applicati.")
    gestione_pct: float | None = Field(
        None,
        description="Commissioni di gestione e altri costi amministrativi o di esercizio, % annua (costi correnti).")
    transazione_pct: float | None = Field(None, description="Costi di transazione, % annua.")
    performance_pct: float | None = Field(
        None, description="Commissioni di performance, % annua. 0 se non previste.")
    incidenza_annua_pct: float | None = Field(
        None,
        description="Incidenza annuale dei costi (RIY) in caso di uscita al periodo di detenzione raccomandato, %.")


class Scenari(BaseModel):
    """Rendimento medio annuo al periodo di detenzione raccomandato, % al netto dei costi."""

    stress_pct: float | None = None
    sfavorevole_pct: float | None = None
    moderato_pct: float | None = None
    favorevole_pct: float | None = None


class DatiKid(BaseModel):
    nome_prodotto: str = Field(description="Nome del prodotto, compresa l'eventuale classe di quote.")
    isin: str | None = Field(None, description="Codice ISIN, 12 caratteri.")
    ideatore: str | None = Field(None, description="Ideatore del PRIIP (società di gestione o emittente).")
    tipo: TipoProdotto = Field(description="fondo comune/SICAV, ETF quotato o certificato/prodotto strutturato.")
    sri: int | None = Field(None, description="Indicatore sintetico di rischio, intero da 1 a 7.")
    periodo_detenzione_anni: float | None = Field(
        None, description="Periodo di detenzione raccomandato in anni (60 mesi → 5).")
    costi: Costi
    scenari: Scenari = Field(description="Scenari di performance al periodo di detenzione raccomandato.")


CAMPI = [
    "nome_prodotto", "isin", "ideatore", "tipo", "sri", "periodo_detenzione_anni",
    "costi.ingresso_pct", "costi.uscita_pct", "costi.gestione_pct", "costi.transazione_pct",
    "costi.performance_pct", "costi.incidenza_annua_pct",
    "scenari.stress_pct", "scenari.sfavorevole_pct", "scenari.moderato_pct", "scenari.favorevole_pct",
]


def valore(d: DatiKid, campo: str):
    x = d
    for parte in campo.split("."):
        x = getattr(x, parte)
    return x
