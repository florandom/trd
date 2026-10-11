# TRD Guida operativa per il cliente

Aggiornamento del 11 ottobre 2026 | Versione fase 5 | Ambiente locale di simulazione

TRD mette a disposizione un centro di controllo per consultare lo stato del sistema, preparare le configurazioni e scegliere le fonti Telegram. È disponibile anche l’analisi consultiva con un simulatore locale: riconosce un formato preciso, registra gli esiti e spiega perché una proposta si ferma. La raccolta reale richiede prima che il team colleghi un account Telegram. I fornitori IA esterni e l’invio di ordini al broker restano disabilitati.

Questa guida descrive l’utilizzo disponibile oggi, i controlli da verificare e le azioni da richiedere al team in caso di problemi. Viene aggiornata insieme alle funzionalità del prodotto.

## Funzionalità disponibili

| Funzione | Disponibilità attuale |
| --- | --- |
| Accesso e uscita | Disponibili con utenti autorizzati e ruoli distinti |
| Consultazione delle pagine | Disponibile per amministratori e lettori |
| Fonti Telegram | Inserimento, rinomina, autorizzazione e disattivazione dalla dashboard |
| Lettura dei messaggi | Implementata e collaudata con dati di prova; richiede credenziali e account Telegram collegato |
| Messaggi Telegram | Consultazione di un’anteprima del testo e dell’evento più recente, con numero di versione |
| Configurazioni e registro attività | Modifiche confermate e registrate; limiti di rischio modificabili soltanto in senso più restrittivo |
| Analisi messaggi | Classificazione locale, motivi di arresto e collegamento alle proposte; collaudata con dati di prova |
| Agenti IA | Attivazione confermata del simulatore locale; configurazioni inizialmente disattivate |
| IA esterna e broker | Disabilitati; richiedono le rispettive verifiche successive |

## Accesso e ruoli

Apri la dashboard all’indirizzo comunicato dal team. Nell’installazione locale è http://localhost:3000. Inserisci l’email e la password del tuo utente. Il team deve predisporre un’utenza nominativa; le credenziali iniziali del server non devono essere condivise fra clienti.

L’amministratore può consultare le pagine e proporre modifiche. Il lettore può consultare i dati e non dispone dei controlli per salvare configurazioni. Anche il servizio verifica il ruolo: un controllo nascosto nella pagina non costituisce l’unica protezione.

La sessione termina dopo trenta minuti di inattività oppure, comunque, dopo otto ore dall’accesso. In caso di scadenza accedi nuovamente. Usa Esci quando hai finito, soprattutto su un dispositivo condiviso. Il ripristino della password e la gestione degli utenti richiedono attualmente l’intervento del team.

## Inserire una fonte Telegram

1. Apri Fonti Telegram e seleziona Aggiungi fonte.
2. Inserisci un nome riconoscibile, ad esempio Segnali del gruppo principale.
3. Inserisci @nomecanale, un link pubblico come https://t.me/nomecanale oppure l’identificativo negativo del gruppo fornito dal team.
4. Imposta Lettura dei messaggi su Autorizzata per consentire la raccolta, oppure su Disattivata per preparare una fonte senza leggerla.
5. Seleziona Rivedi modifica, controlla il riepilogo e scegli Conferma e salva.

Il salvataggio autorizza la fonte, ma non dimostra ancora che il collegamento sia riuscito. La verifica avviene attraverso l’account Telegram collegato dal team. Per i gruppi privati l’account deve avere già accesso: il sistema non utilizza link di invito e non si iscrive automaticamente. Se serve l’identificativo di un gruppo, chiedilo al team.

Una fonte già registrata può essere rinominata o disattivata con Apri fonte. Il riferimento al canale resta fisso per mantenere la provenienza dei messaggi: per cambiare canale, disattiva la fonte precedente e aggiungine una nuova. Sono previste al massimo trentadue fonti per ambiente.

I numeri di telefono, i codici di accesso e la password Telegram non vanno inseriti nella dashboard. Il collegamento dell’account viene eseguito dal team attraverso una procedura locale protetta.

## Verificare lo stato della lettura

| Stato della fonte | Significato e azione |
| --- | --- |
| In attesa del collegamento | La fonte è salvata; l’account o la verifica non sono ancora disponibili |
| Lettura verificata | Una lettura recente è riuscita; controlla anche Ultima verifica |
| Recupero in corso | Il servizio sta recuperando una parte della cronologia |
| Interruzione da verificare | La pausa supera la finestra di recupero; il team deve valutare il periodo non coperto |
| Fonte non accessibile | Il canale non è disponibile o l’account non dispone dell’accesso necessario |
| Attesa richiesta da Telegram | Telegram richiede una pausa; non occorre reinserire la fonte |
| Da verificare | L’osservazione è troppo vecchia o manca una conferma recente |
| Disattivata | Il servizio non raccoglie nuovi messaggi da questa fonte |

Se lo stato resta inatteso, aggiorna i dati e segnala al team il nome della fonte, lo stato e l’ora dell’ultima verifica. Un dato già caricato non cambia necessariamente da solo: usa Aggiorna dati per consultare una nuova osservazione. Le date della dashboard sono mostrate nel fuso orario italiano.

## Consultare i messaggi e le revisioni

Apri Messaggi Telegram per consultare la fonte, l’identificativo del messaggio, il tipo di evento e la versione più recente. La pagina mostra un’anteprima di testo fino a 240 caratteri. Non scarica allegati e non apre automaticamente i link contenuti nei messaggi.

La ricezione ripetuta dello stesso evento non aggiunge una nuova versione. Una modifica effettiva conserva una nuova revisione. Una cancellazione viene indicata come tale, mantenendo gli identificativi e lo storico necessari alla ricostruzione. Il numero di messaggi della fonte conta i messaggi distinti, anche quando esistono più revisioni.

La raccolta viene verificata periodicamente; l’impostazione iniziale è ogni trenta secondi, ma la durata dipende dalle fonti e dalle risposte di Telegram. Dopo una pausa il recupero copre inizialmente una finestra massima di ventiquattro ore. Le revisioni o cancellazioni molto vecchie e gli eventi avvenuti e scomparsi durante un’interruzione possono non essere recuperabili. Un’interruzione oltre questa finestra viene resa visibile.

I messaggi sono dati da valutare. La pagina Analisi messaggi mostra l’esito della classificazione e i motivi di arresto. Le proposte riconosciute compaiono anche in Segnali, con le versioni e le valutazioni consultive. Nessun messaggio o risultato del simulatore autorizza un ordine.

## Consultare e configurare l’analisi locale

In Analisi messaggi seleziona Aggiorna dati per leggere gli ultimi esiti. Ignorato indica che non è stato riconosciuto un segnale; Richiede revisione indica un formato ambiguo, una modifica, una risposta o una configurazione incompleta; Scaduto indica un messaggio troppo vecchio. In attesa indica una proposta consultiva che non dispone ancora di una verifica del rischio e di dati di mercato verificati.

Il riconoscimento iniziale richiede un solo strumento Forex supportato, direzione, prezzo di ingresso, stop loss e take profit. Il formato deve essere completo e preciso: intervalli di prezzo, più obiettivi, suffissi dello strumento o istruzioni aggiunte richiedono revisione. Il sistema non indovina prezzi o strumenti. La finestra iniziale dell’analisi è di quindici minuti dalla pubblicazione, distinta dal recupero della cronologia Telegram.

L’amministratore può aprire Agenti IA e attivare Analisi locale per Classificazione dei segnali, Interpretazione dei segnali, Analisi di mercato e Valutazione delle decisioni. Ogni attivazione passa da Rivedi modifica e Conferma e salva; il riepilogo mostra anche la nuova versione delle istruzioni. Gli agenti necessari devono essere tutti configurati. La Verifica critica può essere aggiunta, mentre la Revisione delle posizioni resta indisponibile. Il lettore può consultare le configurazioni senza modificarle.

Il simulatore restituisce attesa perché non osserva quotazioni o conti reali. Apri dettaglio permette di consultare prezzi della proposta, stato e tentativi degli agenti, con modello e versione. I costi del simulatore sono zero; la pagina Costi IA distingue consumi registrati e prenotazioni conservate quando un tentativo è rimasto senza esito confermato. Un riavvio non reinvia automaticamente una richiesta dall’esito sconosciuto.

Modifiche e cancellazioni conservano lo storico e fermano le proposte non inviate. Le risposte a un messaggio richiedono revisione: non producono una seconda proposta di apertura. Disattivare una fonte impedisce nuove elaborazioni autorizzate da quella fonte. Una configurazione modificata durante l’analisi richiede una nuova verifica.

## Modificare le configurazioni

Ogni salvataggio amministrativo richiede un riepilogo e una conferma. La conferma vale per due minuti ed è legata all’utente, all’ambiente, ai valori proposti e alla versione corrente. Se un altro amministratore ha modificato gli stessi dati, aggiorna la pagina e rivedi la proposta.

Nei Controlli del rischio puoi preparare limiti più restrittivi di quelli correnti. Non puoi aumentare la capacità autorizzata dal server, eliminare gli stop obbligatori o attivare il trading reale. Con esposizioni già presenti, le modifiche del rischio richiedono il futuro servizio di esecuzione e vengono rifiutate.

In Impostazioni puoi preparare i periodi di conservazione. La pulizia dei contenuti Telegram e IA viene avviata dal team ed è limitata a piccoli lotti; gli identificativi e le evidenze necessarie alle operazioni restano protetti. Il periodo dei log grezzi è già configurabile, ma la cancellazione dei log per età non è ancora implementata. La rotazione per dimensione e numero di file è attiva.

Il Registro attività permette di ricostruire gli accessi e le modifiche. Le versioni precedenti sono conservate: per correggere un valore effettua una nuova modifica confermata. Le conferme impediscono salvataggi involontari, ma non sostituiscono la verifica del contenuto proposto.

## Controlli prima di un utilizzo operativo

Oggi l’installazione resta in simulazione, con automazione e trading reale disattivati. Uno stato positivo nella panoramica conferma la disponibilità dell’infrastruttura; non conferma la salute di un broker o la validità finanziaria di un messaggio.

Prima di utilizzare la raccolta reale, il team deve collegare l’account Telegram, verificare l’accesso alle fonti e controllare ricezione, modifiche, cancellazioni e recupero dopo un’interruzione. Per l’utilizzo con un broker serviranno inoltre il motore di rischio, la riconciliazione, i test sul conto demo e le verifiche del server di destinazione. L’abilitazione del trading reale non è disponibile come semplice interruttore della dashboard.

## Cronologia degli aggiornamenti

9 ottobre 2026 — Prima guida cliente mantenuta nel progetto. Descrive accesso, configurazioni confermate, gestione delle fonti dalla dashboard e raccolta Telegram della fase 4. Il collegamento a un account reale è ancora da predisporre.

11 ottobre 2026 — Aggiunta l’analisi consultiva della fase 5: esiti dei messaggi, proposte, attivazione confermata del simulatore, revisione delle modifiche e visibilità dei tentativi e delle prenotazioni. IA esterna e trading restano disabilitati.
