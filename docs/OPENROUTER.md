# OpenRouter per analisi consultiva

Aggiornamento del 12 ottobre 2026. Adapter, collaudo esplicito, modelli immutabili e contabilizzazione sono implementati e verificati con trasporto sintetico. Nessun account o modello reale è stato collaudato in questa installazione. Il default resta AI_PROVIDER_MODE=mock con budget zero; integrare OpenRouter non abilita trading o dati di mercato.

## Account e manifest

Preparare account e chiave OpenRouter dedicati all’ambiente, credito disponibile e limite di spesa nel provider. La chiave va solo al servizio AI sul VPS, mai su Vercel o nel browser. Copiare infra/openrouter/manifest.example.json in una directory privata ignorata; sostituire tutti i valori indicativi. Il file pubblico è volutamente scaduto e non contiene un modello utilizzabile.

Il manifest fissa modello/versione, identificativo immutabile, tag esatto dell’endpoint provider, nome esatto del provider restituito dalla risposta, schema, token, prezzi massimi in USD per milione e pricing_version. Impostare reviewed_at/expires_at UTC entro sette giorni e l’ambiente corretto. Scegliere nuovi id e pricing_version ad ogni revisione di prezzi, provider, scadenza o limite. Non vengono riscritti modelli già importati, nemmeno se un operatore li ha disabilitati.

Il catalogo dell’endpoint deve confermare structured_outputs, response_format, max_tokens, stato attivo, capacità di output e prezzi a token entro i limiti approvati. I prezzi per richiesta non sono supportati. input_token_limit deve coprire l’intero contesto pubblicato di tutti gli endpoint con quel tag, entro AI_HARD_MAX_INPUT_TOKENS. Questo limite conservativo permette una prenotazione dimostrabile senza stimare token con un tokenizer diverso da quello del provider. [Catalogo endpoint ufficiale](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model)

## Collaudo e import

Mantenere AI_PROVIDER_MODE=mock durante la preparazione. Compilare OPENROUTER_API_KEY e quattro budget server positivi: AI_HARD_MAX_COST_PER_REQUEST_USD, AI_HARD_DAILY_BUDGET_USD, AI_HARD_MONTHLY_BUDGET_USD e AI_HARD_DAILY_BUDGET_PER_AGENT_USD. Tutti sono stringhe decimali. La configurazione deve coprire il costo massimo dei probe prima della prima chiamata.

```sh
pnpm ai:accept --operator-env private/staging/operator.env --manifest private/staging/manifest.json --receipt data/ai/acceptance-staging-v1.json --allow-paid-probe
pnpm ai:import --operator-env private/staging/operator.env --receipt data/ai/acceptance-staging-v1.json --admin-email admin@example.test
```

L’email dell’esempio va sostituita con un amministratore TRD attivo dello stesso ambiente. Il primo comando è un’azione operatore esplicita che può generare addebiti: legge il catalogo e invia tre prove sintetiche per modello, senza ritentativi e senza messaggi Telegram. Prima della rete controlla il massimo per richiesta e il massimo aggregato rispetto ai budget configurati. I probe sono fuori dal registro dei job applicativi: eventuali esecuzioni ripetute vanno controllate tramite il limite del provider e la sua fatturazione.

La ricevuta viene scritta soltanto se tutti i probe restituiscono WAIT/NO_MARKET_CONTEXT con provenienza, schema, token e costo verificati. È legata ad ambiente, hash del manifest, impronta della chiave e scadenza; non contiene la chiave. Un fallimento non crea una ricevuta nuova e non attiva agenti. Proteggere la ricevuta come configurazione operatore: non è una firma che resiste a un amministratore del server ostile.

L’import usa esclusivamente la credenziale di migrazione e richiede un amministratore esistente; registra i modelli con audit e non riceve la chiave OpenRouter. Ripetere lo stesso import è idempotente; modificare il profilo richiede una nuova identità di modello. Non importare in un database o ambiente diverso dalla ricevuta.

## Attivazione controllata

Configurare OPENROUTER_ACCEPTANCE_PATH con il percorso privato visibile dal worker e AI_PROVIDER_MODE=openrouter, poi riavviare soltanto il worker. Il servizio rifiuta ricevute scadute, ambienti diversi, chiavi cambiate o limiti di input superiori a quelli del server. OPENROUTER_MANIFEST_PATH può conservare il percorso del manifest operativo; il comando richiede comunque --manifest esplicito e il runtime autorizza i profili della ricevuta.

Dalla dashboard ADMIN scegliere il modello approvato per Analisi di mercato, Valutazione delle decisioni o Verifica critica, impostare un costo massimo positivo per richiesta e confermare il riepilogo. Classificazione e interpretazione restano deterministiche/locali; Revisione delle posizioni resta indisponibile. Il simulatore richiede costo massimo zero. La selezione dalla dashboard non può approvare un account, modificare prezzi o aggirare il collaudo operatore.

Le chiamate usano un’origine HTTPS fissa, schema JSON rigoroso, un solo provider consentito, allow_fallbacks=false, require_parameters=true, data_collection=deny, zdr=true e max_price. Nessun tool, plugin, redirect, recupero di URL o richiesta di ragionamento privato. Solo prompt fisso e proposta normalizzata sono trasmessi; il testo Telegram grezzo non viene inviato. Se il routing privacy richiesto non è disponibile, la richiesta fallisce. Le impostazioni tecniche vanno verificate anche nelle condizioni dell’account/provider. [Output strutturati](https://openrouter.ai/docs/guides/features/structured-outputs), [routing provider](https://openrouter.ai/docs/guides/routing/provider-selection)

## Costi e arresti

Ogni tentativo prenota in PostgreSQL l’intero input_token_limit e l’output massimo consentito. I budget globali UTC, mensili, per agente e per richiesta rimangono serializzati. Il costo contabilizzato conservativamente è il maggiore fra stima dai token ai prezzi approvati e usage.cost; il costo dichiarato dal provider è conservato separatamente, arrotondato sempre verso l’alto a dieci decimali. Cache e reasoning sono sottoinsiemi dei token, senza doppio conteggio. [Usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)

Se usage o cost mancano, il risultato non è utilizzabile, l’importo rimane UNKNOWN e le alternative si fermano. Un costo noto superiore alla prenotazione aumenta l’importo trattenuto e ferma il percorso. Il blocco sopravvive a riavvio e cambio periodo; non esiste ancora uno sblocco automatico. Generation ID e provider sono registrati per la futura riconciliazione, senza salvare risposte grezze o reasoning privato.

Al massimo tre tentativi per job e agente, comprese le ripartenze. Alternative applicative solo se configurate e revisionate, con consumo precedente confermato; nessun fallback interno OpenRouter. Quota, rate limit, timeout e consumo sconosciuto interrompono i tentativi. Tutti gli agenti condividono il deadline del job. Il contratto OpenAI diretto precedente resta disponibile soltanto nei test offline.

Prima dell’uso con dati autorizzati, verificare nel provider credito, fatturazione, limiti, risposta reale, schema, routing privacy e comportamento di timeout/429/402; valutare gli esiti su fixture approvate. Il probe sintetico verifica il protocollo e non certifica la qualità finanziaria di un modello. Anche PROPOSE resta una proposta consultiva senza approvazione del rischio o ordine: la fase 6 e MT5 non sono ancora implementati.
