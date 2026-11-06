"""Confronto fra prodotti e coerenza con il profilo MiFID del cliente.

Il profilo è quello prodotto da mifid-advisory (``GET /clienti/{id}/profilo`` → ``dettagli``): classe di rischio
con i suoi limiti (SRI massimo, costo annuo ragionevole), orizzonte, classi di strumenti ammesse in base a
conoscenza ed esperienza. I controlli sono un primo filtro per il consulente, non una verifica di adeguatezza
completa, che resta quella di mifid-advisory sul portafoglio.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .schema import DatiKid, TipoProdotto

OK, ATTENZIONE, KO = "ok", "attenzione", "ko"
CLASSE_STRUMENTO = {TipoProdotto.fondo: "fondi_etf", TipoProdotto.etf: "fondi_etf",
                    TipoProdotto.certificato: "certificati"}
SOGLIA_COSTOSO = 1.5  # incidenza oltre 1,5 volte la mediana dei prodotti dello stesso tipo


@dataclass
class Segnalazione:
    controllo: str
    esito: str
    dettaglio: str


@dataclass
class Valutazione:
    codice: str
    dati: DatiKid
    costo_annuo_pct: float | None
    costo_periodo_eur: float | None  # costi stimati su 10.000 euro nel periodo di detenzione raccomandato
    rango_costo: int  # 1 = il più costoso del confronto
    segnalazioni: list[Segnalazione] = field(default_factory=list)

    @property
    def esito(self) -> str:
        esiti = {s.esito for s in self.segnalazioni}
        return KO if KO in esiti else ATTENZIONE if ATTENZIONE in esiti else OK


def _pct(x: float) -> str:
    return f"{x:.2f}%".replace(".", ",")


def valuta_prodotti(prodotti: dict[str, DatiKid], profilo: dict | None = None) -> list[Valutazione]:
    """Valutazioni ordinate dal prodotto più costoso al meno costoso."""
    per_tipo: dict[TipoProdotto, list[float]] = {}
    for d in prodotti.values():
        if d.costi.incidenza_annua_pct is not None:
            per_tipo.setdefault(d.tipo, []).append(d.costi.incidenza_annua_pct)
    mediane = {t: statistics.median(v) for t, v in per_tipo.items()}
    ordinati = sorted(prodotti.items(), key=lambda kv: -(kv[1].costi.incidenza_annua_pct or 0))

    risultati = []
    for rango, (codice, d) in enumerate(ordinati, start=1):
        riy = d.costi.incidenza_annua_pct
        rhp = d.periodo_detenzione_anni
        v = Valutazione(codice, d, riy, round(100 * riy * rhp, 0) if riy is not None and rhp else None, rango)
        mancanti = [n for n, x in [("SRI", d.sri), ("periodo di detenzione", rhp), ("incidenza dei costi", riy)]
                    if x is None]
        if mancanti:
            v.segnalazioni.append(Segnalazione("Dati", ATTENZIONE, "Non estratti: " + ", ".join(mancanti)))
        if riy is not None and len(per_tipo.get(d.tipo, [])) >= 3 and riy > SOGLIA_COSTOSO * mediane[d.tipo]:
            v.segnalazioni.append(Segnalazione(
                "Costi", ATTENZIONE, f"Incidenza annua {_pct(riy)}, oltre {SOGLIA_COSTOSO:g} volte la mediana dei "
                                     f"prodotti di tipo {d.tipo.value} ({_pct(mediane[d.tipo])})"))
        if profilo:
            v.segnalazioni.extend(_coerenza(d, profilo))
        risultati.append(v)
    return risultati


def _coerenza(d: DatiKid, profilo: dict) -> list[Segnalazione]:
    out = []
    limiti = profilo.get("limiti", {})
    sri_max, costo_max = limiti.get("sri_max"), limiti.get("costo_max")
    if d.sri is not None and sri_max is not None:
        out.append(Segnalazione("Rischio", OK if d.sri <= sri_max else KO,
                                f"SRI {d.sri} su 7, massimo per il profilo {profilo.get('nome', '')} {sri_max}"))
    orizzonte = profilo.get("orizzonte_anni")
    if d.periodo_detenzione_anni is not None and orizzonte is not None:
        rhp = d.periodo_detenzione_anni
        esito = OK if rhp <= orizzonte else ATTENZIONE if rhp <= orizzonte + 2 else KO
        out.append(Segnalazione("Orizzonte", esito,
                                f"Periodo di detenzione raccomandato {rhp:g} anni, orizzonte del cliente {orizzonte} "
                                "anni"))
    ammesse = profilo.get("classi_ammesse")
    if ammesse is not None:
        classe = CLASSE_STRUMENTO[d.tipo]
        out.append(Segnalazione("Conoscenza ed esperienza", OK if classe in ammesse else KO,
                                f"{'Ammesso' if classe in ammesse else 'Non ammesso'}: la classe "
                                f"'{classe.replace('_', ' ')}' "
                                f"{'rientra' if classe in ammesse else 'non rientra'} fra quelle che il cliente "
                                "conosce dal questionario"))
    if costo_max is not None and d.costi.incidenza_annua_pct is not None:
        riy = d.costi.incidenza_annua_pct
        out.append(Segnalazione("Costi rispetto al profilo", OK if riy <= costo_max * 100 else ATTENZIONE,
                                f"Incidenza annua {_pct(riy)}, riferimento del profilo {_pct(costo_max * 100)}"))
    return out


def carica_profilo(percorso: str | Path) -> dict:
    import json
    return json.loads(Path(percorso).read_text(encoding="utf-8"))


def profilo_da_mifid(url: str, email: str, password: str, cliente_id: int, timeout: float = 10) -> dict:
    """Profilo di un cliente letto dall'API di mifid-advisory (progetto 4)."""
    with httpx.Client(base_url=url.rstrip("/"), timeout=timeout) as c:
        r = c.post("/auth/token", data={"username": email, "password": password})
        r.raise_for_status()
        intestazioni = {"Authorization": f"Bearer {r.json()['access_token']}"}
        cliente = c.get(f"/clienti/{cliente_id}", headers=intestazioni)
        cliente.raise_for_status()
        p = c.get(f"/clienti/{cliente_id}/profilo", headers=intestazioni)
        p.raise_for_status()
        dettagli = p.json()["dettagli"]
        dati = cliente.json()
        dettagli["cliente"] = f"{dati.get('nome', '')} {dati.get('cognome', '')}".strip()
        return dettagli
