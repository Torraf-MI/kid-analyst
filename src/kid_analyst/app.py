"""Interfaccia Streamlit: ``streamlit run src/kid_analyst/app.py``.

La chiave API si legge da ANTHROPIC_API_KEY (o dai secrets di Streamlit). Senza chiave l'app funziona con
l'estrattore a regole e la ricerca estrattiva.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from kid_analyst import estrattore_regole, rag
from kid_analyst.confronto import ATTENZIONE, KO, OK, carica_profilo, valuta_prodotti
from kid_analyst.costi_api import BudgetSuperato, Registro
from kid_analyst.pdf import leggi_pdf

RADICE = Path(__file__).resolve().parents[2]
DATASET = RADICE / "dataset"
RISULTATI = RADICE / "risultati"
SIMBOLI = {OK: "🟢", ATTENZIONE: "🟡", KO: "🔴"}
MOTORI = {"Regole (gratuito)": None, "Claude Haiku 5.5 · testo": ("claude-haiku-5-5", "testo"),
          "Claude Haiku 5.5 · PDF": ("claude-haiku-5-5", "pdf"), "Claude Opus 5.5 · PDF": ("claude-opus-5-5", "pdf")}

st.set_page_config(page_title="Analista KID", page_icon="📄", layout="wide")


def _chiave() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:  # nessun file di secrets
        return None


@st.cache_resource
def _client(chiave: str):
    import anthropic
    return anthropic.Anthropic(api_key=chiave)


@st.cache_data
def _indice_dataset() -> list[dict]:
    return json.loads((DATASET / "indice.json").read_text(encoding="utf-8"))


chiave = _chiave()
client = _client(chiave) if chiave else None
if "registro" not in st.session_state:
    st.session_state.registro = Registro(budget_usd=1.0)
    st.session_state.estratti = {}
registro: Registro = st.session_state.registro

with st.sidebar:
    st.header("Analista KID")
    st.caption("Estrazione strutturata, confronto dei costi, coerenza con il profilo MiFID e domande con "
               "citazione della pagina.")
    st.write("Chiave API Claude:", "✅ presente" if client else "— assente (solo regole e ricerca estrattiva)")
    registro.budget_usd = st.number_input("Budget della sessione ($)", 0.05, 20.0, registro.budget_usd, 0.05)
    s = registro.sintesi()
    st.metric("Spesa API", f"${s['spesa_usd']:.4f}", f"{s['chiamate']} chiamate · {s['da_cache']} dalla cache",
              delta_color="off")
    st.caption("KID sintetici: società, prodotti e valori sono simulati.")

documenti_tab, confronto_tab, domande_tab, accuratezza_tab = st.tabs(
    ["📄 Documenti", "⚖️ Confronto e profilo", "💬 Domande", "🎯 Accuratezza"])

with documenti_tab:
    indice = _indice_dataset()
    etichette = {f"{v['codice']} · {v['nome']}": v["codice"] for v in indice}
    c1, c2 = st.columns([3, 2])
    scelti = c1.multiselect("KID del dataset", list(etichette), default=list(etichette)[:9])
    caricati = c2.file_uploader("Oppure carica dei KID in PDF", type="pdf", accept_multiple_files=True)
    motore = st.radio("Estrattore", list(MOTORI), horizontal=True,
                      disabled=False, help="I modelli Claude richiedono la chiave API")
    if MOTORI[motore] and not client:
        st.info("Per usare Claude imposta ANTHROPIC_API_KEY; intanto puoi usare l'estrattore a regole.")
    if st.button("Estrai i dati", type="primary", disabled=bool(MOTORI[motore] and not client)):
        docs = [leggi_pdf(DATASET / "kid" / f"{etichette[e]}.pdf") for e in scelti]
        docs += [leggi_pdf(f.getvalue(), Path(f.name).stem) for f in caricati or []]
        if MOTORI[motore]:
            from kid_analyst.estrattore_claude import EstrattoreClaude
            modello, modalita = MOTORI[motore]
            e = EstrattoreClaude(client, modello, modalita, "low", registro, RADICE / ".cache_llm")
            estrai = e.estrai
        else:
            def estrai(d):
                return estrattore_regole.estrai(d), 0.0
        st.session_state.estratti, st.session_state.documenti = {}, {d.codice: d for d in docs}
        barra = st.progress(0.0)
        for i, d in enumerate(docs, 1):
            try:
                st.session_state.estratti[d.codice] = estrai(d)[0]
            except BudgetSuperato as ex:
                st.error(f"Budget esaurito: {ex}")
                break
            except Exception as ex:
                st.warning(f"{d.codice}: {ex}")
            barra.progress(i / len(docs))
        st.session_state.motore = motore
        st.rerun()

    estratti = st.session_state.estratti
    if estratti:
        st.subheader(f"Dati estratti · {st.session_state.get('motore', '')}")
        righe = []
        for codice, d in estratti.items():
            c, s_ = d.costi, d.scenari
            righe.append({"Codice": codice, "Prodotto": d.nome_prodotto, "Tipo": d.tipo.value, "ISIN": d.isin,
                          "SRI": d.sri, "Periodo (anni)": d.periodo_detenzione_anni,
                          "Incidenza annua %": c.incidenza_annua_pct, "Ingresso %": c.ingresso_pct,
                          "Uscita %": c.uscita_pct, "Gestione %": c.gestione_pct, "Transazione %": c.transazione_pct,
                          "Performance %": c.performance_pct, "Stress %": s_.stress_pct,
                          "Sfavorevole %": s_.sfavorevole_pct, "Moderato %": s_.moderato_pct,
                          "Favorevole %": s_.favorevole_pct})
        st.dataframe(pd.DataFrame(righe), hide_index=True, use_container_width=True)
        st.caption("«None» indica un valore che l'estrattore non ha trovato nel documento.")

with confronto_tab:
    estratti = st.session_state.estratti
    if not estratti:
        st.info("Estrai prima i dati di alcuni KID nella scheda Documenti.")
    else:
        profili = {"Nessun profilo": None} | {
            f"{p.stem.capitalize()} – {carica_profilo(p).get('nome')}": p for p in sorted((DATASET / "profili").glob(
                "*.json"))}
        c1, c2 = st.columns([2, 3])
        scelta = c1.selectbox("Profilo del cliente (da mifid-advisory)", list(profili), index=2)
        proprio = c2.file_uploader("Oppure carica il JSON del profilo (GET /clienti/{id}/profilo → dettagli)",
                                   type="json")
        profilo = json.load(proprio) if proprio else (carica_profilo(profili[scelta]) if profili[scelta] else None)
        if profilo:
            lim = profilo.get("limiti", {})
            st.write(f"**{profilo.get('cliente', 'Cliente')}** · classe {profilo['classe']} {profilo['nome']} · "
                     f"SRI massimo {lim.get('sri_max')} · orizzonte {profilo['orizzonte_anni']} anni · "
                     f"strumenti ammessi: {', '.join(profilo['classi_ammesse']).replace('_', ' ')}")
        valutazioni = valuta_prodotti(estratti, profilo)
        tabella = pd.DataFrame([{
            "#": v.rango_costo, "Esito": f"{SIMBOLI[v.esito]} {v.esito}", "Prodotto": v.dati.nome_prodotto,
            "Costo annuo %": v.costo_annuo_pct, "Costi su 10.000 €": v.costo_periodo_eur, "SRI": v.dati.sri,
            "Anni": v.dati.periodo_detenzione_anni,
            "Da verificare": ", ".join(s.controllo for s in v.segnalazioni if s.esito != OK)}
            for v in valutazioni])
        st.dataframe(tabella, hide_index=True, use_container_width=True, column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "Prodotto": st.column_config.TextColumn(width="large"),
            "Costo annuo %": st.column_config.NumberColumn(format="%.2f"),
            "Costi su 10.000 €": st.column_config.NumberColumn(format="%.0f")})
        grafico = pd.DataFrame({"Prodotto": [v.dati.nome_prodotto[:42] for v in valutazioni],
                                "Incidenza annua dei costi %": [v.costo_annuo_pct or 0 for v in valutazioni]})
        st.bar_chart(grafico, x="Prodotto", y="Incidenza annua dei costi %", horizontal=True, height=360,
                     sort="-Incidenza annua dei costi %")
        for v in valutazioni:
            with st.expander(f"{SIMBOLI[v.esito]} {v.dati.nome_prodotto}"):
                for s_ in v.segnalazioni:
                    st.write(f"{SIMBOLI[s_.esito]} **{s_.controllo}** · {s_.dettaglio}")
                if not v.segnalazioni:
                    st.write("Nessuna segnalazione.")
        st.caption("Primo filtro per il consulente: la verifica di adeguatezza completa resta quella di "
                   "mifid-advisory, sul portafoglio proposto.")

with domande_tab:
    documenti = st.session_state.get("documenti", {})
    if not documenti:
        st.info("Estrai prima i dati di alcuni KID nella scheda Documenti: le domande si fanno su quei documenti.")
    else:
        titoli = {c: d.nome_prodotto for c, d in st.session_state.estratti.items()}
        indice_rag = rag.Indice(list(documenti.values()), titoli)
        esempi = ["Quali sono i costi di uscita del primo certificato?",
                  "Cosa succede se l'emittente non è in grado di pagare?",
                  "Quale ETF ha l'incidenza annua dei costi più bassa?"]
        domanda = st.text_input("Domanda", placeholder=esempi[0])
        st.caption("Esempi: " + " · ".join(esempi))
        if domanda:
            with st.spinner("Cerco nei documenti…"):
                try:
                    r = rag.rispondi(indice_rag, domanda, client, registro,
                                     tabella=rag.riepilogo(st.session_state.estratti))
                except BudgetSuperato as ex:
                    st.error(f"Budget esaurito: {ex}")
                    r = None
            if r:
                (st.success if r.generata else st.info)(r.testo)
                for i, f in enumerate(r.fonti, 1):
                    dove = "tabella dei dati estratti" if f.pagina == 0 else f"pagina {f.pagina}"
                    st.markdown(f"**[{i}] {f.titolo}**, {dove}")
                    st.caption(f.citazione[:400].replace("*", "\\*").replace("\n", " "))
                if r.costo_usd:
                    st.caption(f"Costo della risposta: ${r.costo_usd:.4f}")

with accuratezza_tab:
    file = sorted(RISULTATI.glob("*.json"))
    if not file:
        st.info("Nessun risultato: esegui `kid-analyst valuta`.")
    else:
        rapporti = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in file}
        sintesi = pd.DataFrame([{
            "Estrattore": r["sintesi"]["estrattore"], "Campi corretti": r["sintesi"]["accuratezza_campi"],
            "KID senza errori": r["sintesi"]["documenti_perfetti"],
            **{f"Layout {k}": v for k, v in r["sintesi"]["per_impaginazione"].items()},
            "Costo per KID ($)": r["sintesi"]["costo_medio_usd"], "Secondi per KID": r["sintesi"]["secondi_medi"]}
            for r in rapporti.values()])
        formati = {c: "{:.1%}" for c in sintesi.columns if c.startswith(("Campi", "KID", "Layout"))}
        formati |= {"Costo per KID ($)": "{:.4f}", "Secondi per KID": "{:.1f}"}
        st.dataframe(sintesi.style.format(formati), hide_index=True, use_container_width=True)
        st.caption("30 KID sintetici, 16 campi ciascuno. Le regole sono scritte sui layout tabellare e discorsivo; "
                   "il layout grafico (SRI solo come casella evidenziata, scenari trasposti) fa da layout nuovo.")
        nome = st.selectbox("Dettaglio per campo", list(rapporti))
        per_campo = pd.DataFrame({"Campo": list(rapporti[nome]["sintesi"]["per_campo"]),
                                  "Accuratezza": list(rapporti[nome]["sintesi"]["per_campo"].values())})
        st.bar_chart(per_campo, x="Campo", y="Accuratezza", horizontal=True, height=420, sort=False)
        errori = [{"KID": d["codice"], "Layout": d["impaginazione"], "Campo": e["campo"],
                   "Atteso": str(e["atteso"]), "Trovato": str(e["trovato"])}
                  for d in rapporti[nome]["documenti"] for e in d["errori"]]
        if errori:
            st.write(f"{len(errori)} campi errati")
            st.dataframe(pd.DataFrame(errori), hide_index=True, use_container_width=True)
