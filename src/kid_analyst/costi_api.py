"""Controllo dei costi delle chiamate a Claude: prezzi, stima preventiva, budget e cache su disco.

* La stima preventiva usa l'endpoint di conteggio dei token (gratuito) e rifiuta la chiamata se il costo massimo
  possibile supera il budget residuo.
* La cache su disco evita di pagare due volte la stessa estrazione: la chiave è l'impronta del PDF più modello,
  modalità, effort e versione del prompt.
* Il registro somma i token e i dollari effettivi letti da ``response.usage``.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

# Dollari per milione di token (input, output), listino Claude API di novembre 2026.
PREZZI = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class BudgetSuperato(RuntimeError):
    pass


def costo(modello: str, token_input: int, token_output: int) -> float:
    p_in, p_out = PREZZI[modello]
    return (token_input * p_in + token_output * p_out) / 1_000_000


@dataclass
class Registro:
    """Spesa della sessione, con un tetto in dollari."""

    budget_usd: float = 1.00
    spesa_usd: float = 0.0
    chiamate: int = 0
    token_input: int = 0
    token_output: int = 0
    da_cache: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def residuo(self) -> float:
        return self.budget_usd - self.spesa_usd

    def autorizza(self, modello: str, token_input: int, max_output: int) -> float:
        """Costo massimo possibile della chiamata; eccezione se non sta nel budget residuo."""
        massimo = costo(modello, token_input, max_output)
        if massimo > self.residuo:
            raise BudgetSuperato(f"La chiamata può costare fino a ${massimo:.4f}, budget residuo ${self.residuo:.4f}")
        return massimo

    def registra(self, modello: str, usage) -> float:
        speso = costo(modello, usage.input_tokens, usage.output_tokens)
        with self._lock:
            self.spesa_usd += speso
            self.chiamate += 1
            self.token_input += usage.input_tokens
            self.token_output += usage.output_tokens
        return speso

    def sintesi(self) -> dict:
        return {"chiamate": self.chiamate, "da_cache": self.da_cache, "token_input": self.token_input,
                "token_output": self.token_output, "spesa_usd": round(self.spesa_usd, 4),
                "budget_usd": self.budget_usd}


class Cache:
    def __init__(self, cartella: Path | None):
        self.cartella = cartella
        if cartella:
            cartella.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def chiave(*parti: str) -> str:
        return hashlib.sha256("|".join(parti).encode()).hexdigest()[:32]

    def leggi(self, chiave: str) -> dict | None:
        if not self.cartella:
            return None
        f = self.cartella / f"{chiave}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def scrivi(self, chiave: str, valore: dict) -> None:
        if self.cartella:
            (self.cartella / f"{chiave}.json").write_text(json.dumps(valore, ensure_ascii=False), encoding="utf-8")
