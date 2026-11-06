"""Lettura dei PDF: testo pagina per pagina, conservando il numero di pagina per le citazioni."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


@dataclass
class Pagina:
    numero: int  # da 1
    testo: str


@dataclass
class Documento:
    codice: str
    pagine: list[Pagina]
    contenuto: bytes = field(repr=False)

    @property
    def impronta(self) -> str:
        return hashlib.sha256(self.contenuto).hexdigest()

    @property
    def testo(self) -> str:
        return "\n".join(p.testo for p in self.pagine)

    def testo_con_pagine(self) -> str:
        """Testo con i separatori di pagina, per i modelli che leggono il testo invece del PDF."""
        return "\n\n".join(f"[Pagina {p.numero}]\n{p.testo}" for p in self.pagine)


def leggi_pdf(sorgente: str | Path | bytes, codice: str | None = None) -> Documento:
    if isinstance(sorgente, bytes):
        contenuto = sorgente
        codice = codice or hashlib.sha256(contenuto).hexdigest()[:10]
    else:
        percorso = Path(sorgente)
        contenuto = percorso.read_bytes()
        codice = codice or percorso.stem
    with pdfplumber.open(io.BytesIO(contenuto)) as pdf:
        pagine = [Pagina(i + 1, (p.extract_text() or "").strip()) for i, p in enumerate(pdf.pages)]
    return Documento(codice, pagine, contenuto)
