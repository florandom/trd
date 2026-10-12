"""Build the offline Italian flow diagram and shared SVG illustrations.

Then rasterize the SVG files for Markdown and Word using the document runtime.
No application services, accounts or credentials are accessed.
"""

# Long lines are generated SVG markup and the self-contained HTML/CSS template.
# ruff: noqa: E501

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs/illustrazioni"


def text(x, y, lines, size=22, color="#23324a", weight=400):
    return "".join(
        f'<text x="{x}" y="{y + i * (size + 9)}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(line)}</text>'
        for i, line in enumerate(lines)
    )


def box(x, y, width, height, title, lines, fill="#ffffff", stroke="#d8e2ea", dashed=False):
    dash = ' stroke-dasharray="8 6"' if dashed else ""
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>'
        + text(x + 20, y + 38, [title], 23, weight=700)
        + text(x + 20, y + 74, lines, 20)
    )


def arrow(path, dashed=False):
    return (
        f'<path d="{path}" fill="none" stroke="#708399" stroke-width="2.5" marker-end="url(#arrow)"'
        + (' stroke-dasharray="7 6"' if dashed else "")
        + "/>"
    )


def svg(content, height, title, description):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-labelledby="title desc"><title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#708399"/></marker></defs><rect width="1200" height="{height}" rx="24" fill="#f4f7fa"/><g font-family="Arial, sans-serif">{content}</g></svg>'''


STEPS = [
    ("Telegram", ["Fonti autorizzate", "Account collegato"]),
    ("Raccolta", ["Salva e deduplica", "Conserva revisioni"]),
    ("Interpretazione", ["Segnale completo?", "Recente e iniziale?"]),
    ("Agenti IA", ["Analisi e decisione", "Critica se prevista"]),
    ("Dashboard", ["Esiti e motivi", "Proposte e costi"]),
]


def flow():
    parts = text(
        24, 38, ["PERCORSO ATTUALE  ·  Dopo configurazione e attivazione esplicite"], 20, weight=700
    )
    for i, (title, lines) in enumerate(STEPS):
        parts += box(
            24 + i * 234,
            80,
            216,
            140,
            f"{i + 1}  {title}",
            lines,
            fill="#eef6fc" if i in (0, 4) else "#ffffff",
        )
        if i < 4:
            parts += arrow(f"M {240 + i * 234} 150 H {252 + i * 234}")
    parts += arrow("M 600 220 V 260")
    parts += box(
        352,
        272,
        496,
        96,
        "Si ferma se non supera i controlli",
        ["Ignorato, scaduto, revisione o rifiuto"],
        "#fff3de",
        "#e3bb74",
    )
    parts += text(612, 252, ["No"], 18)
    parts += arrow("M 848 320 H 1068 V 226")
    parts += text(
        26,
        410,
        ["NESSUN ORDINE REALE  ·  Rischio ed esecuzione simulata verificati in locale."],
        23,
        "#7a4d12",
        700,
    )
    parts += text(
        26,
        454,
        ["FASE 7 VERIFICATA  ·  Laboratorio isolato; MT5 e broker reale restano futuri"],
        20,
        "#596a80",
        700,
    )
    parts += box(
        24,
        482,
        350,
        100,
        "Rischio locale",
        ["Prenotazioni e controlli"],
        "#eef6fc",
        "#d8e2ea",
        False,
    )
    parts += box(
        425, 482, 350, 100, "Bridge e simulatore", ["Ordini, stop e chiusure"], "#eef6fc", "#d8e2ea", False
    )
    parts += box(
        826, 482, 350, 100, "MT5 e broker reale", ["Da implementare e collaudare"], "#f4f7fa", "#b1bdc9", True
    )
    parts += arrow("M 378 532 H 416") + arrow("M 779 532 H 816", True)
    return svg(
        parts,
        610,
        "Come TRD tratta un segnale",
        "Telegram autorizzato, raccolta, interpretazione rigorosa, agenti consultivi e dashboard. Rischio, bridge firmato e ordini simulati sono verificati nel laboratorio locale. MT5 e broker reale restano futuri.",
    )


def components():
    parts = text(
        24,
        38,
        ["ARCHITETTURA  ·  La dashboard controlla, i processi persistenti elaborano"],
        21,
        weight=700,
    )
    parts += box(
        24,
        80,
        348,
        118,
        "Dashboard italiana",
        ["Locale oggi; Vercel predisposto", "Utenti ADMIN e VIEWER"],
        "#eef6fc",
    )
    parts += box(
        430,
        80,
        326,
        118,
        "API autenticata",
        ["Sessioni, ruoli e conferme", "Remoto con Access e MFA"],
    )
    parts += box(
        814,
        80,
        362,
        118,
        "PostgreSQL",
        ["Stato, versioni e audit", "Ruoli e credenziali distinti"],
        "#eef6fc",
    )
    parts += arrow("M 378 139 H 420") + arrow("M 762 139 H 804")
    parts += box(
        24,
        270,
        348,
        118,
        "Collector Telegram",
        ["Account e sessione cifrata", "Solo fonti autorizzate"],
    )
    parts += box(430, 270, 326, 118, "Worker IA", ["Simulatore oggi", "OpenRouter dopo collaudo"])
    parts += box(
        814, 270, 362, 118, "Manutenzione", ["Pulizia a lotti manuale", "Credenziale dedicata"]
    )
    parts += arrow("M 198 264 V 230 H 995 V 204")
    parts += arrow("M 593 264 V 230") + arrow("M 995 264 V 204")
    parts += text(
        25, 434, ["Il backend resta persistente su Windows o Linux. Il bridge resta isolato."], 22
    )
    parts += text(
        25,
        472,
        ["FASE 7  ·  Rischio e bridge paper verificati. MT5 e avvisi restano futuri."],
        22,
        "#7a4d12",
        700,
    )
    return svg(
        parts,
        500,
        "Componenti e responsabilità di TRD",
        "Dashboard e API autenticate, PostgreSQL e processi separati per Telegram, IA e manutenzione. Rischio locale con dati di prova. Credenziali separate; accesso remoto e OpenRouter da collaudare sugli account reali. Bridge paper verificato nel laboratorio locale; MT5 e avvisi sono futuri.",
    )


DETAILS = [
    (
        "01",
        "Telegram",
        "Il cliente sceglie le fonti",
        "L’amministratore aggiunge canali e gruppi nella dashboard e conferma la lettura. Il team collega l’account Telegram in locale. Nei gruppi privati l’account deve già avere accesso; TRD non si iscrive da solo.",
        "Configurazione reale richiesta",
    ),
    (
        "02",
        "Raccolta",
        "Un messaggio, uno storico",
        "Il collector salva messaggi, elimina duplicati e conserva modifiche e cancellazioni osservate. Non apre link né scarica allegati. Default: lettura ogni 30 secondi, recupero fino a 24 ore; gli eventi non osservati possono mancare.",
        "Implementata e verificata con dati di prova",
    ),
    (
        "03",
        "Interpretazione",
        "Si procede solo con un formato preciso",
        "Classificazione e interpretazione restano locali. Servono un messaggio iniziale non di risposta, un solo strumento riconosciuto, ingresso, stop loss e take profit coerenti. Default: 15 minuti dalla pubblicazione. Ambiguità, istruzioni extra, modifiche e risposte richiedono revisione; il sistema non inventa dati.",
        "Implementata e verificata con dati di prova",
    ),
    (
        "04",
        "Agenti IA",
        "Valutazioni consultive",
        "Dopo il riconoscimento, analisi di mercato e valutazione della decisione elaborano la proposta. La critica si aggiunge se attivata; se obbligatoria dal server, la sua assenza ferma il percorso. Tutti gli agenti necessari devono essere configurati. Il simulatore gratuito restituisce attesa, senza mercato o conto verificati.",
        "Attivazione esplicita richiesta",
    ),
    (
        "05",
        "Dashboard",
        "Il cliente vede il risultato",
        "Analisi messaggi e Segnali mostrano esito, prezzi, motivi e tentativi. Costi IA distingue costo contabilizzato, costo del fornitore e importi prenotati. Le modifiche richiedono riepilogo e conferma; un lettore consulta senza salvare. Una proposta positiva resta consultiva. Nel laboratorio separato, il servizio rischio autorizza comandi simulati. Posizioni mostra stop, chiusure complete e risultati; ogni richiesta amministrativa richiede conferma.",
        "Nessun ordine al broker",
    ),
]


def html(flow_svg):
    details = "".join(
        f"""<details class="step" {"open" if number == "03" else ""}><summary><span class="number">{number}</span><span><b>{escape(title)}</b><small>{escape(subtitle)}</small></span><span class="plus" aria-hidden="true">+</span></summary><div class="body"><p>{escape(body)}</p><p class="status">{escape(status)}</p></div></details>"""
        for number, title, subtitle, body, status in DETAILS
    )
    mobile = "".join(
        f"<li><b>{i + 1}. {escape(title)}</b><span>{escape(' · '.join(lines))}</span></li>"
        for i, (title, lines) in enumerate(STEPS)
    )
    return (
        """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>TRD Come funziona il sistema</title>
<style>
:root{--ink:#20314a;--muted:#58697b;--blue:#22608c;--line:#dbe3e9;--paper:#faf9f6;--white:#fff;--amber:#815419}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1240px;margin:auto;padding:40px 32px 28px}header{display:flex;justify-content:space-between;align-items:center;gap:16px}.brand{font-size:20px;font-weight:800;letter-spacing:.12em}.tag,.status{font-size:13px;font-weight:600;color:var(--blue)}.tag{border:1px solid var(--line);border-radius:99px;padding:6px 14px;background:white}.eyebrow{margin:36px 0 8px;text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700;color:var(--muted)}h1{font-size:clamp(32px,4vw,48px);line-height:1.12;letter-spacing:-.04em;margin:0 0 18px;max-width:850px}h2{font-size:25px;line-height:1.25;margin:34px 0 12px}p{margin:0 0 16px}.intro{max-width:850px;color:var(--muted);font-size:18px}.notice{display:flex;align-items:center;gap:12px;padding:14px 18px;border-radius:14px;background:#fff0d5;color:var(--amber);margin:24px 0}.dot{width:10px;height:10px;border-radius:50%;background:#bc7c20;flex:none}nav{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0}a{color:var(--blue);text-underline-offset:3px}nav a{border:1px solid var(--line);border-radius:10px;padding:8px 14px;background:white;text-decoration:none;font-size:14px;font-weight:600}a:hover{color:#0b3b60}a:focus-visible,summary:focus-visible{outline:3px solid #3286b8;outline-offset:4px}figure{margin:0}.map svg{width:100%;height:auto;display:block}figcaption{font-size:13px;color:var(--muted);margin:10px 0 22px}.mobile-flow{display:none}.steps{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}.step{border:1px solid var(--line);border-radius:16px;background:white;overflow:hidden}summary{cursor:pointer;display:flex;align-items:center;gap:14px;padding:18px;list-style:none}summary::-webkit-details-marker{display:none}.number{font-size:14px;font-weight:700;align-self:flex-start;color:var(--blue);background:#eef6fc;border-radius:10px;padding:5px 9px}summary b{display:block;font-size:18px}summary small{display:block;font-size:14px;color:var(--muted)}.plus{margin-left:auto;color:var(--blue);font-size:24px}.step[open] .plus{transform:rotate(45deg)}.body{padding:0 18px 4px 67px;color:var(--muted);font-size:15px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:32px}.columns h3{font-size:18px;margin:10px 0}.columns p,.columns li{font-size:15px;color:var(--muted)}ul{padding-left:20px;margin:0 0 16px}li{margin:7px 0}code{font:13px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere;background:#eef2f5;padding:3px 5px;border-radius:5px}.example{display:block;padding:14px;margin:14px 0}footer{border-top:1px solid var(--line);margin-top:34px;padding-top:20px;font-size:13px;color:var(--muted)}section{scroll-margin-top:20px}@media(max-width:650px){main{padding:22px 18px}header{align-items:flex-start}.tag{font-size:11px}.eyebrow{margin-top:28px}.notice{align-items:flex-start}.steps,.columns{grid-template-columns:1fr}.columns{gap:8px}.map svg{display:none}.mobile-flow{display:grid;gap:10px;list-style:none;padding:0;margin:0}.mobile-flow li{margin:0;border:1px solid var(--line);background:white;border-radius:14px;padding:12px 16px;position:relative}.mobile-flow li+li:before{content:'↓';position:absolute;top:-16px;left:50%;color:var(--blue);background:var(--paper);line-height:20px}.mobile-flow span{display:block;color:var(--muted);font-size:14px}.body{padding-left:18px}h2{font-size:23px}}@media print{body{background:white}main{padding:0}.notice{border:1px solid var(--line)}nav{display:none}.step{break-inside:avoid}.body{display:block}details:not([open])>.body{display:block}h2{break-after:avoid}figure{break-inside:avoid}}
</style></head><body><main><header><span class="brand">TRD</span><span class="tag">Fase 7 · 12 ottobre 2026</span></header><p class="eyebrow">Guida visiva per il cliente</p><h1>Da un messaggio Telegram<br>a una proposta da valutare</h1><p class="intro">TRD legge fonti autorizzate, riconosce segnali precisi e registra valutazioni consultive. Qui trovi il percorso attuale, il ruolo degli agenti IA e le regole che fermano il sistema.</p><div class="notice"><span class="dot" aria-hidden="true"></span><span><strong>Oggi nessun ordine al broker.</strong> Laboratorio locale con ordini simulati verificato; API e credenziali esterne rinviate ai test finali.</span></div><nav aria-label="Sezioni del diagramma"><a href="#flusso">Il flusso</a><a href="#passaggi">Esplora i passaggi</a><a href="#regole">Regole e costi</a><a href="#futuro">Cosa manca per operare</a></nav><section id="flusso" aria-labelledby="flow-heading"><h2 id="flow-heading">Il percorso attuale</h2><figure class="map">"""
        + flow_svg
        + '<ol class="mobile-flow" aria-label="Sequenza del segnale">'
        + mobile
        + """</ol><figcaption>Il percorso parte solo con fonte autorizzata, account collegato e agenti necessari attivi. Un controllo non superato ferma l’analisi; l’esito resta visibile nella dashboard. Il laboratorio separato verifica rischio e ordini simulati. Solo il collegamento tratteggiato a MT5 e broker reale resta futuro.</figcaption></figure></section><section id="passaggi"><h2>Esplora i cinque passaggi</h2><p>Apri un passaggio per vedere cosa succede e chi lo prepara.</p><div class="steps">"""
        + details
        + """</div></section><section id="regole"><h2>Regole e costi</h2><div class="columns"><article><h3>Prima di una proposta</h3><ul><li>Fonte autorizzata e account con accesso al canale.</li><li>Un solo segnale completo, iniziale e recente.</li><li>Direzione, ingresso, stop loss e take profit coerenti.</li><li>Agenti richiesti configurati; nessuna fase obbligatoria saltata.</li></ul><p>Formato sintetico, solo illustrativo:</p><code class="example">BUY EURUSD ENTRY 1.10000 SL 1.09500 TP 1.11000</code><p>Strumenti riconosciuti nel testo: EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD. Nessuna autorizzazione finanziaria deriva da questo elenco.</p></article><article><h3>IA esterna e spesa</h3><p>Classificazione e interpretazione restano locali. OpenRouter può servire analisi, decisione e critica dopo collaudo, import del modello e selezione confermata. Al fornitore arriva la proposta normalizzata, non il testo Telegram completo.</p><ul><li>Simulatore: costo zero e risposta di attesa.</li><li>Modello esterno: approvazione valida, costo massimo e budget server.</li><li>Consumo sconosciuto: importo trattenuto e altri tentativi fermati.</li><li>Riavvio: nessuno sblocco automatico delle prenotazioni.</li></ul><p>Le credenziali restano nei servizi competenti. La dashboard mostra esiti e costi; le modifiche richiedono conferma.</p></article></div></section><section id="futuro"><h2>Cosa manca per operare sul mercato</h2><div class="columns"><article><h3>Configurazioni e prove reali</h3><p>Telegram, OpenRouter e accesso remoto sono implementati e verificati con dati di prova. Servono account autorizzati, verifiche di privacy e fatturazione, dominio protetto e MFA, oltre al collaudo sul server reale.</p><p>Le fonti si configurano dalla dashboard. Il collegamento Telegram resta una procedura locale del team; il bot degli avvisi è una funzione futura separata.</p></article><article><h3>Rischio ed esecuzione simulata verificati</h3><p>Il motore del rischio è implementato e verificato con dati di prova: valuta conto, mercato, stop, lotti e limiti. Il laboratorio locale collega dati firmati, prenotazioni, comandi, stop, chiusure complete e riconciliazione. Non richiede account esterni e non invia ordini reali. MT5 e broker richiedono implementazione e test demo.</p><p>I limiti nella dashboard sono preparatori e possono essere resi più restrittivi. Il trading reale richiederà autorizzazioni indipendenti dopo i test demo: nessun risultato IA può abilitarlo.</p></article></div></section><footer>Revisione del 12 ottobre 2026 · Europe/Rome · File autonomo senza servizi esterni. Per le procedure usa la guida cliente o la guida di preparazione del team.</footer></main></body></html>"""
    )


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    flow_svg = flow()
    (ASSETS / "flusso-segnale.svg").write_text(flow_svg, encoding="utf-8")
    (ASSETS / "componenti-sistema.svg").write_text(components(), encoding="utf-8")
    (ROOT / "docs/cliente/FLUSSO_SISTEMA.html").write_text(html(flow_svg), encoding="utf-8")


if __name__ == "__main__":
    main()
