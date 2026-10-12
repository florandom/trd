# TRD Guida cliente

Aggiornamento del 12 ottobre 2026 | Fase 7 | Analisi e ordini simulati in locale

TRD raccoglie messaggi da fonti Telegram autorizzate, riconosce segnali strutturati e mostra analisi e motivi di arresto nella dashboard. **Oggi non invia ordini al broker.** L’installazione resta locale, con simulatore gratuito, raccolta Telegram e agenti disattivati finché non vengono configurati.

## Il percorso di un segnale

![Flusso da Telegram alla dashboard con controlli e arresto prima degli ordini](../illustrazioni/flusso-segnale.png)

Apri il [diagramma interattivo](FLUSSO_SISTEMA.html) nel browser per esplorare ogni passaggio. Funziona anche senza connessione.

## Cosa è disponibile oggi

| Funzione | Stato e limite |
| --- | --- |
| Dashboard e utenti | Implementati e verificati in locale; amministratore modifica, lettore consulta |
| Fonti e messaggi Telegram | Implementati e verificati con dati di prova; account reale da collegare e collaudare |
| Classificazione e interpretazione | Locali, con formato rigoroso; attivazione esplicita degli agenti |
| Analisi e decisione IA | Consultive; simulatore disponibile, senza dati di mercato verificati |
| OpenRouter e accesso remoto | Implementati e verificati con dati di prova; account, dominio, MFA e collaudo reale ancora richiesti |
| Rischio ed esecuzione simulata | Collegati e verificati nel laboratorio locale: dati firmati, prenotazioni, ordini simulati e recupero |
| MT5 e ordini reali | Da implementare e collaudare; trading disabilitato |

## Accedere e scegliere le fonti

1. Apri l’indirizzo comunicato dal team; in locale è `http://localhost:3000`. Usa email e password personali. Il lettore consulta; l’amministratore salva modifiche confermate.
2. In **Fonti Telegram**, scegli **Aggiungi fonte**. Inserisci nome e riferimento: `@nomecanale`, link pubblico o identificativo del gruppo fornito dal team.
3. Imposta la lettura su **Autorizzata**, poi **Rivedi modifica** e **Conferma e salva**. Per i gruppi privati l’account deve già avere accesso. TRD non si iscrive automaticamente.
4. Controlla **Lettura verificata** e **Ultima verifica**. Una fonte salvata può essere ancora in attesa del collegamento. Usa **Aggiorna dati** per leggere lo stato recente.

Il team collega Telegram con una procedura locale: **telefono, codici e password Telegram non vanno nella dashboard**. Puoi rinominare o disattivare una fonte; per cambiare canale aggiungine una nuova. Massimo 32 fonti per ambiente.

La sessione TRD scade dopo 30 minuti di inattività o 8 ore totali. Usa **Esci** sui dispositivi condivisi; utenti e recupero password richiedono il team. Il tema chiaro o scuro è selezionabile anche all’accesso e su mobile: la scelta resta nel browser per un anno. Le date sono mostrate nel fuso italiano.

Per l’accesso remoto usa il dominio protetto consegnato dal team, completa MFA e accedi a TRD con la stessa email autorizzata. Staging e produzione hanno dati e account separati; produzione non significa trading reale.

## Capire messaggi e analisi

In **Messaggi Telegram** trovi anteprima, fonte, evento e versione. TRD conserva revisioni e cancellazioni osservate, evita duplicati e non apre link né scarica allegati. La lettura iniziale è ogni 30 secondi; il recupero dopo una pausa copre fino a 24 ore. Eventi scomparsi prima dell’osservazione o fuori finestra possono mancare.

Un segnale deve contenere direzione, strumento, ingresso, stop loss e take profit. Esempio inventato, solo per spiegare il formato:

`BUY EURUSD ENTRY 1.10000 SL 1.09500 TP 1.11000`

Sono riconosciuti EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD e NZDUSD. Questo elenco riguarda il testo; non autorizza operazioni. Il segnale iniziale deve essere completo, non una risposta e pubblicato da non più di 15 minuti. Intervalli, suffissi, più obiettivi o istruzioni extra richiedono revisione. Modifiche e cancellazioni fermano la proposta precedente; le risposte non aprono una seconda proposta.

| Esito o stato | Significato e azione |
| --- | --- |
| Ignorato | Non è stato riconosciuto un segnale |
| Richiede revisione | Testo ambiguo, risposta, modifica o configurazione incompleta; verifica con il team |
| Scaduto | Superata la finestra per l’analisi del segnale |
| In attesa | Proposta consultiva; nell’avvio normale mancano conto e mercato verificati. Nessun ordine reale |
| Fonte non accessibile o interruzione da verificare | Comunica al team fonte, stato e ora |
| Attesa richiesta da Telegram | Il servizio rispetta la pausa; non reinserire la fonte |

## Agenti IA e costi

Il percorso usa **classificazione → interpretazione → analisi di mercato → valutazione della decisione**. La **verifica critica** si aggiunge se attivata; se il server la rende obbligatoria, la sua assenza ferma l’analisi. La revisione delle posizioni resta futura.

L’amministratore configura gli agenti in **Agenti IA** con riepilogo e conferma. Non si attivano da soli. Il simulatore costa zero e restituisce attesa perché non osserva mercato o conto. In **Segnali**, apri il dettaglio per vedere prezzi, motivi e tentativi.

OpenRouter richiede collaudo del team, modello approvato non scaduto e costo massimo positivo entro i budget server. Può servire analisi, decisione e critica; classificazione e interpretazione restano locali. Al fornitore va la proposta normalizzata, non il testo Telegram completo. Le chiavi API restano sul server.

**Costi IA** distingue costo contabilizzato, costo del fornitore e importi prenotati. Un consumo sconosciuto conserva la prenotazione e ferma altri tentativi; chiedi al team la riconciliazione. Un riavvio non libera l’importo né reinvia automaticamente quella richiesta. Anche un esito positivo dell’IA non autorizza un ordine.

## Regole e protezioni

Ogni modifica amministrativa richiede conferma, valida per 2 minuti e legata alla versione corrente. Se un altro amministratore ha modificato i dati, aggiorna e rivedi. Il **Registro attività** conserva accessi e cambiamenti.

Nei **Controlli del rischio** puoi preparare limiti più restrittivi: non puoi aumentare l’autorità del server, eliminare gli stop obbligatori o abilitare il trading reale. Il motore è implementato e verificato con dati di prova: controlla stop, rischio, perdita giornaliera, esposizione, lotti, leva, spread e orari. **Il laboratorio locale** collega rischio e ordini simulati, con dati e chiavi temporanei; il team può provarlo senza tuoi account. Un esito incerto conserva il rischio e ferma nuove operazioni fino alla riconciliazione. Nel laboratorio, limiti più restrittivi fermano i comandi non inviati; esposizioni esterne restano soggette a verifica futura.

In **Impostazioni** scegli la conservazione. Il team avvia la pulizia dei contenuti Telegram e IA a piccoli lotti; la pulizia automatica periodica e quella dei log per età non sono disponibili. La rotazione dei log per dimensione è attiva.

Prima della raccolta reale servono collegamento Telegram e prove di lettura, revisioni e recupero. Prima di IA a pagamento e accesso remoto servono account, budget, privacy, dominio e MFA collaudati. Prima di qualsiasi ordine reale serviranno MT5, riconciliazione broker e conto demo verificati; il trading reale richiede ulteriori autorizzazioni indipendenti.

## Cronologia delle revisioni

9 ottobre 2026 — Prima guida con accesso, fonti e raccolta Telegram; account reale da predisporre.

11 ottobre 2026 — Analisi consultiva, agenti locali, tentativi e prenotazioni dei costi; trading disabilitato.

12 ottobre 2026 — Preparazione Vercel, MFA e OpenRouter; account reali da collaudare, rischio e ordini futuri.

12 ottobre 2026 — Tema chiaro e scuro verificato anche all’accesso e su mobile.

12 ottobre 2026 — Guide snellite, diagrammi e rinvii operativi; distinti limiti attuali e funzioni future. Aggiornamenti documentali solo quando necessari.

12 ottobre 2026 — Motore di rischio locale della fase 6 implementato e verificato. Chiariti i controlli e i lotti conservativi; conto, mercato autenticato, esecuzione e MT5 restano futuri. Aggiornati diagrammi e Word.

12 ottobre 2026 — Fase 7: rischio e ordini simulati collegati e verificati in laboratorio locale. API, credenziali esterne e test demo rinviati al collaudo finale; diagrammi e Word aggiornati.
