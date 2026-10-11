# TRD Preparazione pratica per il team di sviluppo

Aggiornamento del 11 ottobre 2026 | Versione fase 5 | Installazione locale e predisposizione delle integrazioni

Questa guida indica cosa predisporre per usare TRD con un cliente: ambiente, account, variabili, chiavi e verifiche. Accesso, dashboard, raccolta Telegram e analisi consultiva locale sono implementati. L’analisi usa un parser rigoroso e un simulatore, con esiti e tentativi registrati nel database. Per Telegram reale mancano ancora credenziali e accesso all’account. Il contratto OpenAI è collaudato soltanto con trasporto simulato; IA esterna, motore di rischio ed esecuzione MT5 richiedono ancora i rispettivi gate.

Le configurazioni future elencate qui preparano il lavoro del team. La presenza di una chiave non dimostra che l’integrazione sia implementata, collegata o autorizzata. Non inserire credenziali reali in questa guida, nei ticket, nei log o negli esempi condivisi.

## Account e accessi da predisporre

| Account o servizio | Cosa predisporre | Quando serve |
| --- | --- | --- |
| Utenti TRD | Amministratore iniziale e utenti nominativi ADMIN o VIEWER | Già ora per la dashboard |
| PostgreSQL | Istanza locale e credenziali distinte per sei ruoli applicativi e operatore | Già ora; create dal setup locale |
| Telegram lettura | Account umano autorizzato dal cliente, accesso alle fonti, API ID e API hash dell’applicazione | Prima di attivare la raccolta reale |
| Provider IA | Account API, progetto dedicato, modello e prezzi verificati, limiti di spesa | Prima del gate esterno; l’analisi locale non richiede chiavi |
| Bot Telegram avvisi | Bot e destinazione di notifica autorizzata | Fase notifiche; separato dall’account di lettura |
| Broker e MT5 | Conto demo, server e login esatti, terminale MT5 e utente Windows dedicato | Fase esecuzione e collaudo demo |
| Server Windows | Accesso amministrativo, account di servizio, storage e backup protetti | Prima del collaudo sul server di destinazione |
| Dominio e Cloudflare | DNS, tunnel e verifica MFA o soluzione equivalente | Prima dell’accesso esterno; il gate attuale lo rifiuta |

Il cliente gestisce canali e gruppi da Fonti Telegram nella dashboard. Il team gestisce l’account di lettura e le credenziali applicative. Non richiedere l’elenco definitivo delle fonti per installare il software: possono essere configurate successivamente dal cliente.

## Preparare l’ambiente locale

Usare Node 24.20.0, pnpm 11.25.0, Python 3.13.16 e uv 0.12.22 con i lockfile del progetto. PostgreSQL deve essere della serie 17. Per lo sviluppo locale sono previsti Docker e Compose; Redis è facoltativo e non detiene stato autorevole.

Eseguire pnpm setup dalla radice del progetto. Il comando crea un file .env privato con password distinte e chiavi casuali; un’esecuzione successiva conserva i valori esistenti. Il modello pubblico e l’inventario dei nomi sono in .env.example. Nei file già creati aggiungere esplicitamente gli eventuali nuovi campi del modello: il setup non riscrive le configurazioni personalizzate.

Avviare docker compose up --build -d. Il servizio initialize prepara i ruoli, applica le migrazioni e crea i valori iniziali senza azzerare i dati. L’indirizzo locale della dashboard è http://localhost:3000. Non rimuovere i volumi per aggiornare il software.

Per gli utenti nominativi eseguire pnpm user:create da un terminale locale interattivo. Il comando accetta ADMIN o VIEWER, non stampa la password e non sovrascrive utenti esistenti. Conservare il bootstrap in modo riservato e assegnare al cliente un accesso personale.

## Variabili necessarie per il nucleo applicativo

| Variabili | Preparazione e valore iniziale |
| --- | --- |
| APP_ENV e ENVIRONMENT_ID | development e local-paper in locale; identificativo coerente tra processi |
| APP_URL e TIMEZONE | http://localhost:3000 ed Europe/Rome; l’origine deve coincidere con quella usata dal browser |
| TRADING_MODE | paper; altri modi vengono ancora rifiutati dai servizi |
| ENABLE_AUTOMATION e ENABLE_LIVE_TRADING | false; non abilitarli per provare Telegram |
| POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD | Nome database, operatore locale e password generata dal setup |
| POSTGRES_HOST e POSTGRES_PORT | 127.0.0.1 e 5432 per lo sviluppo host; Compose usa l’indirizzo interno postgres |
| DATABASE_ADMIN_URL | Credenziale operatore per creare database e ruoli; assente dai runtime |
| MIGRATION_DATABASE_URL | Ruolo trd_migrator per migrazioni e bootstrap; assente dai runtime |
| API_DATABASE_URL e COLLECTOR_DATABASE_URL | Ruoli trd_api e trd_collector con password distinte |
| AI_DATABASE_URL, RISK_DATABASE_URL, MAINTENANCE_DATABASE_URL | Ruoli trd_ai, trd_risk e trd_maintenance con password distinte |
| ADMIN_BOOTSTRAP_EMAIL e ADMIN_BOOTSTRAP_PASSWORD | Utente iniziale e password privata generata; usati solo dal bootstrap |
| AUTH_COOKIE_SECURE | false soltanto nel locale HTTP; in produzione HTTPS è obbligatorio |
| AUTH_SESSION_TTL_SECONDS e AUTH_IDLE_TTL_SECONDS | 28800 e 1800; massimo otto ore assolute e trenta minuti inattive |
| AUTH_MFA_REQUIRED | false; impostarlo a true viene rifiutato perché il MFA locale non è implementato |
| API_PORT, BRIDGE_PORT, DASHBOARD_PORT | 8000, 8001 e 3000; pubblicazione locale su loopback |
| API_INTERNAL_URL | http://127.0.0.1:8000 in sviluppo host; http://api:8000 in Compose |
| LOG_LEVEL, LOG_MAX_BYTES e LOG_BACKUP_COUNT | INFO, 10485760 e 10; log strutturati con redazione delle credenziali |
| REDIS_ENABLED, REDIS_PORT e REDIS_URL | false, 6379 e URL locale; Redis non è necessario alla correttezza |

Ogni URL PostgreSQL deve usare postgresql+psycopg, porta esplicita e il ruolo previsto. Il file .env operatore non viene passato integralmente ai servizi. DATA_DIR e LOG_DIR sono forniti dall’avvio con directory distinte per processo; in produzione devono essere assoluti. ENCRYPTION_KEY è riservata a capacità future del servizio API e non sostituisce la chiave della sessione Telegram.

## Credenziali e collegamento Telegram

Il team o il titolare dell’account deve predisporre un’applicazione nella sezione API development tools di https://my.telegram.org. Registrare TELEGRAM_API_ID e TELEGRAM_API_HASH nel file locale protetto. Sono credenziali dell’applicazione Telegram, distinte dal token di un bot e dagli identificativi dei canali. [Procedura ufficiale Telegram](https://core.telegram.org/api/obtaining_api_id)

| Variabile | Origine o impostazione |
| --- | --- |
| TELEGRAM_ENABLED | false fino all’accesso locale riuscito; true attiva solo la lettura |
| TELEGRAM_API_ID | Intero positivo assegnato all’applicazione Telegram |
| TELEGRAM_API_HASH | Hash applicativo di 32 caratteri esadecimali |
| TELEGRAM_SESSION_ENCRYPTION_KEY | Chiave casuale distinta di 256 bit, codificata con 64 caratteri esadecimali; generata dal setup |
| TELEGRAM_SESSION_KEY_ID | local-v1 inizialmente; cambiare insieme alla chiave quando si esegue una rotazione |
| TELEGRAM_SESSION_PATH | data/telegram.session.enc per l’host; /var/trd/data/telegram.session.enc nel contenitore |
| TELEGRAM_COLLECTOR_IDENTITY | primary; la dashboard prepara fonti per questa identità |
| TELEGRAM_POLL_SECONDS | 30; intervallo configurabile fra 5 e 300 secondi |
| TELEGRAM_BACKFILL_MAX_AGE_SECONDS | 86400; finestra di recupero, fra un minuto e sette giorni |
| TELEGRAM_HISTORY_BATCH_SIZE | 100; da 1 a 100 messaggi per richiesta di cronologia |
| TELEGRAM_REQUEST_TIMEOUT_SECONDS | 20; da 1 a 30 secondi per operazione di rete |
| TELEGRAM_SIGNAL_MAX_AGE_SECONDS | 900; filtro preliminare dei job di analisi, non autorizzazione al trading |

Il numero di telefono, il codice di accesso e l’eventuale password Telegram a due passaggi sono richiesti senza eco dalla procedura locale. Non salvarli in variabili del servizio e non raccoglierli in un modulo della dashboard. La sessione viene cifrata con AES GCM e legata a schema, ambiente, account, identità del collector e identificativo della chiave. La sessione Telethon in memoria non produce un file SQLite in chiaro. [Sessioni Telethon](https://docs.telethon.dev/en/stable/concepts/sessions.html)

Per lo sviluppo host, fermare il collector ed eseguire pnpm telegram:enroll. Impostare poi TELEGRAM_ENABLED=true e avviare nuovamente il servizio. Per Compose, fermare telegram ed eseguire da un terminale interattivo:

```
docker compose stop telegram
docker compose run --rm --no-deps --entrypoint python telegram -m backend.integrations.telegram.enroll
```

L’accesso salva la sessione nel volume Telegram del contenitore, leggibile dal relativo utente di servizio. Non copiare semplicemente la sessione host nel volume senza gestire proprietario e permessi. Dopo l’accesso impostare TELEGRAM_ENABLED=true e ricreare il servizio con docker compose up -d telegram. Quando si eseguono i comandi Compose dopo una modifica a .env, le variabili nuove vengono nuovamente interpolate.

Per sostituire una sessione esistente, fermare prima il collector e invocare il modulo di accesso con --replace-session. Per ruotare la cifratura, fermarlo, configurare la nuova chiave e il nuovo identificativo, poi invocare lo stesso modulo con --rotate-key: richiede la chiave e l’identificativo precedenti in locale e ricifra atomicamente la sessione. Conservare una possibilità di ripristino protetta prima della rotazione. La revoca dall’app Telegram rende la sessione inutilizzabile e richiede un nuovo accesso.

Su macOS e Linux il file sessione deve essere privato con permessi 600. Su Windows predisporre ACL per il solo account del servizio e gli operatori autorizzati. Le ACL del server Windows richiedono un collaudo sul sistema di destinazione.

Il collector conserva nello stesso file cifrato anche gli aggiornamenti interni della sessione richiesti dalla connessione Telegram. Il volume deve quindi restare scrivibile per il suo account di servizio; non sostituirlo con un file montato in sola lettura.

## Verifiche prima della consegna al cliente

1. Verificare migrazione 0005_analysis e servizi locali avviati con i propri ruoli.
2. Provare accesso, uscita e comportamento VIEWER; nessun lettore deve salvare configurazioni.
3. Inserire una fonte autorizzata dalla dashboard, verificare conferma e voce nel Registro attività.
4. Collegare l’account reale e verificare lo stato Lettura verificata con un’osservazione recente.
5. Su una fonte di prova autorizzata, verificare nuovo messaggio, modifica, risposta e cancellazione senza duplicati.
6. Interrompere e riavviare il collector; verificare recupero delle revisioni nella finestra e segnalazione dei periodi non coperti.
7. Verificare Analisi messaggi e il dettaglio delle proposte con agenti locali configurati; mantenere IA esterna, automazione e ordini disabilitati.

Il collector usa una lease PostgreSQL per un solo proprietario attivo dell’account nello stesso database. Ogni scrittura verifica proprietario, generazione, scadenza, ambiente e versione della fonte. Nessuna transazione resta aperta durante una richiesta Telegram. Le limitazioni imposte da Telegram vengono rispettate con un’attesa persistita; perdita del database o della lease impedisce di avanzare il cursore.

La cronologia viene recuperata a lotti in ordine, con controlli sovrapposti e verifiche dei messaggi già registrati per rilevare modifiche e cancellazioni. Il polling non mantiene una coda di aggiornamenti Telethon in memoria. La copertura è limitata alla finestra configurata: non dichiarare recupero completo oltre quella finestra o per eventi spariti prima della prima osservazione. Lease in database diversi non si coordinano: non avviare copie indipendenti dello stesso collector sul medesimo account.

I test automatici usano PostgreSQL 17 e database casuali trd_test_* separati dall’istanza applicativa. I test di protocollo e UI non sostituiscono il collaudo su Telegram reale. Non utilizzare un server PostgreSQL di produzione come TEST_ADMIN_DATABASE_URL.

## Preparare e collaudare l’analisi locale

L’aggiornamento aggiunge la migrazione 0005_analysis. Il worker AI usa il solo ruolo trd_ai e consuma i job Telegram già persistiti. Analisi, proposta, transizioni, audit, outbox e completamento del job vengono confermati atomicamente. Le chiamate al simulatore restano fuori dalle transazioni. Ogni tentativo verifica lease, generazione, fonte, revisione del messaggio e configurazione; un risultato tardivo non può sostituire i dati correnti.

Il bootstrap aggiunge istruzioni immutabili di versione 2 per i cinque agenti implementati, conservando le versioni precedenti e le configurazioni esistenti. Gli agenti non vengono attivati automaticamente. Dalla dashboard ADMIN attivare i quattro agenti di classificazione, interpretazione, analisi e decisione, scegliendo il simulatore locale e confermando la revisione. La conferma seleziona le istruzioni di versione 2. L’agente critico viene eseguito se attivato; se obbligatorio dal server, la sua indisponibilità ferma il percorso. La revisione delle posizioni resta disabilitata.

Il parser accetta un solo messaggio completo nel formato BUY oppure SELL, simbolo, ENTRY, prezzo, SL, prezzo, TP, prezzo. Un esempio di prova è BUY EURUSD ENTRY 1.10000 SL 1.09500 TP 1.11000. Sono riconosciuti EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD e NZDUSD, senza risoluzione di suffissi o mapping al broker. Questo elenco delimita il parser e non approva la negoziazione degli strumenti. I prezzi usano Decimal; controlli economici, quotazioni, conversioni e autorizzazioni per fonte appartengono al futuro gateway del rischio.

| Variabile | Comportamento implementato |
| --- | --- |
| AI_PROVIDER_MODE | Solo mock; altri valori rifiutati all’avvio |
| AI_SIGNAL_MAX_AGE_SECONDS | 900; da 30 a 3600 secondi dalla pubblicazione, ricontrollata alla conclusione |
| AI_JOB_LEASE_SECONDS | 180; da 10 a 300 secondi, oltre il timeout totale più cinque secondi |
| AI_HARD_TIMEOUT_SECONDS | 30; da 1 a 120 secondi per l’intero percorso, incluse le alternative |
| AI_HARD_MAX_OUTPUT_TOKENS | 4096; limite fra 1 e 4096, ristretto dalla configurazione dell’agente |
| AI_HARD_DAILY_BUDGET_USD | 0.00; limite globale giornaliero in USD |
| AI_HARD_MONTHLY_BUDGET_USD | 0.00; limite globale mensile in USD |
| AI_HARD_DAILY_BUDGET_PER_AGENT_USD | 0.00; nuovo limite giornaliero per singolo agente |
| AI_HARD_MAX_COST_PER_REQUEST_USD | 0.00; limite per tentativo, ristretto dal limite dell’agente |
| ENABLE_CRITIC_AGENT | false; true rende obbligatoria la verifica critica con agente configurato |
| ENABLE_ADAPTIVE_MEMORY | false; true resta rifiutato perché la funzione è futura |

Solo il processo AI riceve questi campi. Aggiungere i tre nuovi nomi al file .env esistente se si desidera personalizzarli; altrimenti valgono i default. Dopo una modifica ricreare worker con Compose oppure riavviare il processo host. Conservare i budget a zero per l’installazione locale: il simulatore è gratuito. I valori di spesa richiedono stringhe decimali finite, mai float. Le finestre contabili sono UTC; la dashboard visualizza gli orari in Europe/Rome.

La prenotazione preventiva serializza i limiti globali e per agente in PostgreSQL. Un esito senza consumo confermato conserva l’importo anche dopo cambio di giorno o mese. Un riavvio non ripete un tentativo ancora aperto. Costi IA rende visibili anche le prenotazioni interrotte prima della registrazione del consumo. Per ogni agente sono ammessi al massimo tre tentativi per job, comprese ripartenze e modelli alternativi. Non esiste ancora una procedura operativa per liberare un importo dall’esito sconosciuto: va riconciliato prima di qualsiasi futura attivazione a pagamento.

I test verificano parser, injection, rifiuti, output incompleti, consumi invalidi, spese concorrenti, scadenze, modifiche e permessi su PostgreSQL 17. Per l’uso reale provare in una fonte Telegram autorizzata anche risposte, revisioni e riavvio. Gli esiti del simulatore non validano un modello esterno né certificano una strategia di trading.

## Preparare le integrazioni delle fasi successive

Per l’IA esterna predisporre un account API con progetto e limiti di spesa dedicati. OPENAI_API_KEY è prevista per il primo adapter esterno; una chiave compilata non attiva chiamate. Il contratto Responses usa schema rigoroso, store=false, nessuno strumento e un’origine fissa; oggi accetta soltanto il trasporto di test. Prima di abilitare la rete servono accesso effettivo al modello, manifesti e prezzi attuali verificati, un limite dimostrabile ai token di ingresso, prove di fatturazione e risultati valutati su fixture approvate. La selezione di modelli esterni dalla dashboard è rifiutata. ANTHROPIC_API_KEY, GOOGLE_AI_API_KEY, MOONSHOT_API_KEY e TYPESAFE_API_KEY restano riservati e facoltativi. [Output strutturati OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs)

Per gli avvisi predisporre successivamente un bot tramite BotFather e una destinazione autorizzata. ALERT_TELEGRAM_BOT_TOKEN, ALERT_TELEGRAM_CHAT_ID e ALERT_COOLDOWN_SECONDS riguardano il futuro servizio notifiche; il bot non sostituisce il collector e la fase attuale non invia messaggi. [Creazione di un bot Telegram](https://core.telegram.org/bots#how-do-i-create-a-bot)

Per MT5 predisporre prima un conto demo e un terminale sul server Windows. Le password del broker restano nel terminale. MT5_BRIDGE_SHARED_SECRET e MT5_COMMAND_SIGNING_KEY sono chiavi indipendenti generate dal setup, ma il protocollo di esecuzione non è ancora operativo. Preparare MT5_ALLOWED_ACCOUNT_IDS, MT5_BRIDGE_INSTANCE_ID e MT5_BRIDGE_KEY_ID con l’identità verificata del terminale; MT5_BRIDGE_URL deve essere un’origine HTTPS locale approvata. MT5_COMMAND_TTL_SECONDS, MT5_HEARTBEAT_MAX_AGE_SECONDS, MT5_MAX_CLOCK_SKEW_SECONDS e MANAGED_MAGIC_NUMBER preparano scadenza, freschezza e riconoscimento degli ordini. ENABLE_PENDING_ORDERS e ENABLE_PARTIAL_CLOSE restano false.

I campi HARD_MAX_RISK_PER_TRADE, HARD_MAX_DAILY_LOSS, HARD_MAX_TOTAL_OPEN_RISK, HARD_MAX_OPEN_POSITIONS, HARD_MAX_LOTS e HARD_MAX_EFFECTIVE_LEVERAGE rappresentano l’envelope del server. HARD_REQUIRE_STOP_LOSS e HARD_REQUIRE_TAKE_PROFIT devono restare true. HARD_ALLOWED_SYMBOLS, HARD_MAX_SIGNAL_AGE_SECONDS, HARD_MAX_SPREAD_POINTS e HARD_MAX_SLIPPAGE_POINTS sono predisposti per il futuro motore e non costituiscono oggi controlli esecutivi già verificati. Le frazioni 0.01 e 0.03 rappresentano rispettivamente 1% e 3%; non introdurre numeri a virgola mobile nei contratti finanziari.

Per l’accesso esterno predisporre dominio, DNS, Cloudflare Tunnel e Access o un’alternativa con MFA verificato. CLOUDFLARE_ACCESS_ISSUER e CLOUDFLARE_ACCESS_AUDIENCE sono previsti nelle impostazioni API, ma la verifica degli assertion non è implementata. Il software rifiuta attualmente origini remote in produzione: il team deve completare e collaudare il gate prima di pubblicare l’accesso. Non considerare il solo tunnel come prova di autenticazione applicativa.

## Conservazione manutenzione e backup

RAW_LOG_RETENTION_DAYS, AI_RESPONSE_RETENTION_DAYS e TELEGRAM_RETENTION_DAYS nel modello preparano valori iniziali; i periodi effettivi dei contenuti Telegram e IA vengono letti dalle impostazioni versionate nel database. pnpm retention:run esegue un lotto limitato di pulizia tramite il ruolo maintenance, inclusi i record di autenticazione scaduti. Non è ancora pianificato un esecutore periodico. La cancellazione dei log per età non è implementata; la rotazione per dimensione e numero è attiva. AUDIT_RETENTION_DAYS e TRADE_RETENTION_DAYS non attivano oggi una cancellazione degli audit o delle operazioni.

Predisporre backup cifrati e un test di ripristino prima del rilascio operativo. Conservare la chiave Telegram separatamente dalla sessione cifrata e dai backup ordinari. Escludere .env, sessioni, chiavi, log e dati personali dal repository. Un ripristino non deve abilitare automaticamente il trading o introdurre una seconda istanza attiva sullo stesso account.

## Aggiornare questi documenti

Le fonti mantenute sono docs/cliente/GUIDA_CLIENTE.md e docs/team/GUIDA_PREPARAZIONE.md. Ogni sviluppo che cambia comportamento, controlli, account o variabili richiede l’aggiornamento delle parti interessate, della data e della cronologia, oltre alla rigenerazione dei due file Word. Prima della consegna verificare visivamente tutte le pagine renderizzate. Le istruzioni nel file AGENTS.md della radice rendono questa attività parte del lavoro successivo sul progetto.

Per rigenerare eseguire python infra/scripts/build_guides.py con un interprete che dispone di python-docx, per esempio il runtime documentale di Codex. Questa dipendenza documentale è separata da quelle dei servizi applicativi. Dopo la generazione usare il renderer della skill Documents ed esaminare ogni pagina; la sola creazione del file non conferma la qualità dell’impaginazione.

## Cronologia degli aggiornamenti

9 ottobre 2026 — Prima guida pratica mantenuta nel progetto. Include ruoli e setup esistenti, gestione delle fonti dalla dashboard, accesso locale Telegram, cifratura, recupero a lotti e preparazione delle integrazioni ancora inattive.

11 ottobre 2026 — Aggiunta la preparazione della fase 5 locale: migrazione, parser, istruzioni versionate, attivazioni confermate, limiti del worker, budget e recupero conservativo. Distinti il contratto OpenAI verificato offline e i gate ancora richiesti per rete, rischio e MT5.
