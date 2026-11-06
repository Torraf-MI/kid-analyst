"""Riga di comando: ``kid-analyst genera | estrai | valuta | confronta | chiedi``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import estrattore_regole, rag
from .confronto import carica_profilo, profilo_da_mifid, valuta_prodotti
from .costi_api import Registro
from .pdf import leggi_pdf
from .valutazione import carica_dataset, tabella_markdown, valuta

RADICE = Path(__file__).resolve().parents[2]
DATASET = RADICE / "dataset"
CACHE = RADICE / ".cache_llm"
MOTORI_CLAUDE = ["claude-haiku-5-5:testo:low", "claude-haiku-5-5:pdf:low", "claude-opus-5-5:pdf:low"]


def crea_client():
    """Client Anthropic se è impostata ANTHROPIC_API_KEY, altrimenti None (si lavora senza modello)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic()


def crea_estrattore(motore: str, client, registro: Registro, cache: Path | None = CACHE):
    """``regole`` oppure ``modello:modalità:effort``, per esempio ``claude-opus-5-5:pdf:low``."""
    if motore == "regole":
        return "regole", lambda doc: (estrattore_regole.estrai(doc), 0.0)
    if client is None:
        raise SystemExit(f"Il motore {motore} richiede ANTHROPIC_API_KEY")
    from .estrattore_claude import EstrattoreClaude
    modello, modalita, effort = (motore.split(":") + ["pdf", "low"])[:3]
    e = EstrattoreClaude(client, modello, modalita, effort, registro, cache)
    return e.nome, e.estrai


def _documenti(percorsi: list[str]):
    out = []
    for p in percorsi:
        p = Path(p)
        out.extend(leggi_pdf(f) for f in (sorted(p.glob("*.pdf")) if p.is_dir() else [p]))
    return out


def cmd_genera(a):
    from .generatore import genera_dataset
    kid = genera_dataset(Path(a.cartella), a.n, a.seme)
    print(f"{len(kid)} KID generati in {a.cartella}")


def cmd_estrai(a):
    registro = Registro(a.budget)
    _, estrai = crea_estrattore(a.motore, crea_client(), registro)
    for doc in _documenti(a.pdf):
        dati, costo = estrai(doc)
        print(json.dumps({"documento": doc.codice, "costo_usd": round(costo, 5), **dati.model_dump(mode="json")},
                         ensure_ascii=False, indent=2))
    if registro.chiamate or registro.da_cache:
        print(json.dumps(registro.sintesi()), file=sys.stderr)


def cmd_valuta(a):
    client = crea_client()
    motori = a.motori.split(",") if a.motori else ["regole"] + (MOTORI_CLAUDE if client else [])
    dataset = carica_dataset(Path(a.dataset))
    if a.limite:
        dataset = dataset[: a.limite]
    registro = Registro(a.budget)
    rapporti = []
    for m in motori:
        nome, estrai = crea_estrattore(m, client, registro, None if a.senza_cache else CACHE)
        print(f"→ {nome} su {len(dataset)} KID", file=sys.stderr)
        r = valuta(nome, estrai, dataset, lambda c, e: print(f"  {c}: {e}", file=sys.stderr))
        r.salva(Path(a.uscita) / f"{m.replace(':', '_')}.json")
        rapporti.append(r)
    tabella = tabella_markdown(rapporti)
    (Path(a.uscita) / "valutazione.md").write_text(tabella + "\n", encoding="utf-8")
    print(tabella)
    print(json.dumps(registro.sintesi()), file=sys.stderr)


def _profilo(a) -> dict | None:
    if a.profilo:
        return carica_profilo(a.profilo)
    if a.mifid_url:
        return profilo_da_mifid(a.mifid_url, a.mifid_email, os.environ.get("MIFID_PASSWORD", "demo"), a.cliente)
    return None


def cmd_confronta(a):
    registro = Registro(a.budget)
    _, estrai = crea_estrattore(a.motore, crea_client(), registro)
    prodotti = {doc.codice: estrai(doc)[0] for doc in _documenti(a.pdf)}
    profilo = _profilo(a)
    if profilo:
        print(f"Profilo: {profilo.get('cliente', '')} · classe {profilo['classe']} {profilo['nome']}\n")
    for v in valuta_prodotti(prodotti, profilo):
        costo = f"{v.costo_annuo_pct:.2f}%" if v.costo_annuo_pct is not None else "n.d."
        print(f"{v.rango_costo:>2}. [{v.esito.upper():^10}] {v.dati.nome_prodotto} · costo annuo {costo}")
        for s in v.segnalazioni:
            if s.esito != "ok" or a.tutto:
                print(f"      {s.esito:<10} {s.controllo}: {s.dettaglio}")


def cmd_chiedi(a):
    docs = _documenti(a.pdf)
    titoli = {d.codice: estrattore_regole.estrai(d).nome_prodotto or d.codice for d in docs}
    r = rag.rispondi(rag.Indice(docs, titoli), a.domanda, crea_client(), Registro(a.budget))
    print(r.testo, "\n")
    for i, f in enumerate(r.fonti, 1):
        print(f"[{i}] {f.titolo}, pagina {f.pagina}: «{f.citazione[:160]}»")
    if r.costo_usd:
        print(f"\nCosto: ${r.costo_usd:.4f}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="kid-analyst", description=__doc__)
    sub = p.add_subparsers(dest="comando", required=True)

    g = sub.add_parser("genera", help="genera il dataset di KID sintetici con i valori attesi")
    g.add_argument("--cartella", default=str(DATASET))
    g.add_argument("--n", type=int, default=30)
    g.add_argument("--seme", type=int, default=2026)
    g.set_defaults(f=cmd_genera)

    def comuni(s, motore=True):
        s.add_argument("--budget", type=float, default=1.0, help="spesa massima in dollari (predefinito 1)")
        if motore:
            s.add_argument("--motore", default="regole", help="regole oppure modello:modalità:effort")

    e = sub.add_parser("estrai", help="estrae i dati strutturati da uno o più KID")
    e.add_argument("pdf", nargs="+")
    comuni(e)
    e.set_defaults(f=cmd_estrai)

    v = sub.add_parser("valuta", help="misura l'accuratezza degli estrattori sul dataset")
    v.add_argument("--motori", help="elenco separato da virgole; predefinito: regole e, con la chiave, " +
                   ", ".join(MOTORI_CLAUDE))
    v.add_argument("--dataset", default=str(DATASET))
    v.add_argument("--uscita", default=str(RADICE / "risultati"))
    v.add_argument("--limite", type=int)
    v.add_argument("--senza-cache", action="store_true")
    comuni(v, motore=False)
    v.set_defaults(f=cmd_valuta)

    c = sub.add_parser("confronta", help="confronta i costi e la coerenza con il profilo del cliente")
    c.add_argument("pdf", nargs="+")
    c.add_argument("--profilo", help="profilo MiFID in JSON (formato di mifid-advisory)")
    c.add_argument("--mifid-url", help="URL dell'API di mifid-advisory, in alternativa a --profilo")
    c.add_argument("--mifid-email", default="consulente@demo.it")
    c.add_argument("--cliente", type=int, default=1)
    c.add_argument("--tutto", action="store_true", help="mostra anche i controlli superati")
    comuni(c)
    c.set_defaults(f=cmd_confronta)

    q = sub.add_parser("chiedi", help="domanda in linguaggio naturale con citazione della pagina")
    q.add_argument("domanda")
    q.add_argument("--pdf", nargs="+", default=[str(DATASET / "kid")])
    comuni(q, motore=False)
    q.set_defaults(f=cmd_chiedi)

    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
