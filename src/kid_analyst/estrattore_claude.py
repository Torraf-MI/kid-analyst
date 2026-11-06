"""Estrazione con Claude e output strutturato: la risposta è validata direttamente sul modello Pydantic ``DatiKid``.

Due modalità di input:

* ``pdf``: il PDF intero come blocco ``document``. Claude legge testo e immagine delle pagine, quindi vede anche
  gli elementi grafici (la casella evidenziata della scala di rischio). Costa più token.
* ``testo``: il testo estratto con pdfplumber, pagina per pagina. Costa meno, ma perde ciò che è solo grafico.
"""

from __future__ import annotations

import base64
from pathlib import Path

import anthropic

from .costi_api import Cache, Registro
from .pdf import Documento
from .schema import DatiKid

VERSIONE_PROMPT = "2026-11-05"
MODELLO_PREDEFINITO = "claude-opus-5-5"
MAX_TOKEN = 8000  # il ragionamento adattivo conta nei token di output

ISTRUZIONI = """Leggi un KID PRIIPs (documento contenente le informazioni chiave) ed estrai i dati richiesti
dallo schema.

Regole:
- Percentuali come numeri in punti percentuali: "1,25%" → 1.25; "-2,50 %" → -2.5.
- Una voce di costo indicata come "nessuno", "non applicabile" o "non addebitiamo" vale 0.
- I costi di ingresso e di uscita sono una tantum, in % dell'importo. Gestione, transazione e performance sono % annue.
- L'incidenza annuale dei costi e gli scenari vanno letti nella colonna del periodo di detenzione raccomandato,
  non in quella dell'uscita dopo un anno.
- Gli scenari sono il "rendimento medio per ciascun anno" (non il rimborso in euro).
- Il periodo di detenzione raccomandato va espresso in anni: 60 mesi → 5.
- L'indicatore di rischio (SRI) può essere scritto nel testo o indicato solo graficamente, come casella evidenziata
  di una scala da 1 a 7. Se non è determinabile, lascia null: non indovinare.
- Il tipo è "etf" per i fondi indicizzati quotati, "certificato" per certificati e prodotti strutturati,
  "fondo" per gli altri fondi e SICAV.
- Riporta nome, ISIN e ideatore esattamente come scritti nel documento."""


class ErroreEstrazione(RuntimeError):
    pass


def _contenuto(doc: Documento, modalita: str) -> list[dict]:
    if modalita == "pdf":
        blocco = {"type": "document", "title": doc.codice,
                  "source": {"type": "base64", "media_type": "application/pdf",
                             "data": base64.standard_b64encode(doc.contenuto).decode()}}
    elif modalita == "testo":
        blocco = {"type": "text", "text": f"<documento>\n{doc.testo_con_pagine()}\n</documento>"}
    else:
        raise ValueError(f"Modalità sconosciuta: {modalita}")
    return [blocco, {"type": "text", "text": "Estrai i dati di questo KID."}]


class EstrattoreClaude:
    def __init__(self, client: anthropic.Anthropic | None = None, modello: str = MODELLO_PREDEFINITO,
                 modalita: str = "pdf", effort: str = "low", registro: Registro | None = None,
                 cache: Path | None = None):
        self.client = client or anthropic.Anthropic()
        self.modello, self.modalita, self.effort = modello, modalita, effort
        self.registro = registro or Registro()
        self.cache = Cache(cache)

    @property
    def nome(self) -> str:
        return f"{self.modello} · {self.modalita} · effort {self.effort}"

    def estrai(self, doc: Documento) -> tuple[DatiKid, float]:
        """Dati estratti e costo effettivo in dollari (0 se il risultato arriva dalla cache)."""
        chiave = Cache.chiave(doc.impronta, self.modello, self.modalita, self.effort, VERSIONE_PROMPT)
        if (salvato := self.cache.leggi(chiave)) is not None:
            self.registro.da_cache += 1
            return DatiKid.model_validate(salvato["dati"]), 0.0

        messaggi = [{"role": "user", "content": _contenuto(doc, self.modalita)}]
        conteggio = self.client.messages.count_tokens(model=self.modello, system=ISTRUZIONI, messages=messaggi)
        self.registro.autorizza(self.modello, conteggio.input_tokens, MAX_TOKEN)

        risposta = self.client.messages.parse(
            model=self.modello, max_tokens=MAX_TOKEN, system=ISTRUZIONI, messages=messaggi,
            output_format=DatiKid, output_config={"effort": self.effort},
        )
        speso = self.registro.registra(self.modello, risposta.usage)
        if risposta.stop_reason == "refusal":
            raise ErroreEstrazione(f"{doc.codice}: richiesta rifiutata")
        if risposta.stop_reason == "max_tokens" or risposta.parsed_output is None:
            raise ErroreEstrazione(f"{doc.codice}: risposta incompleta ({risposta.stop_reason})")
        dati = risposta.parsed_output
        self.cache.scrivi(chiave, {"dati": dati.model_dump(mode="json"), "modello": self.modello,
                                   "token_input": risposta.usage.input_tokens,
                                   "token_output": risposta.usage.output_tokens, "costo_usd": speso})
        return dati, speso
