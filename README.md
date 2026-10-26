# Caller Genius · Audit-to-Demo Voice Funnel

MVP FastAPI per audit telefonici, demo AI personalizzate con ElevenLabs/Twilio e appuntamenti su Google Calendar. Include una dashboard italiana e una modalità mock completa. Nessuna chiamata reale viene effettuata con la configurazione predefinita.

## Avvio locale (Python 3.11+)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --no-access-log
```

Apri http://localhost:8000/admin/prospects. Credenziali locali: `admin` / `local-development-password`. Aggiungi un prospect usando i tuoi numeri in formato E.164, premi **Avvia ring audit**, poi **Fai partire Demo Call**. La landing richiede conferma prima di avviare la chiamata. In mock l'audit termina con `no_answer`, viene generato l'outreach e la demo restituisce un conversation ID `mock-*`.

`DRY_RUN=true` **oppure** `MOCK_MODE=true` disabilita tutte le chiamate esterne, incluso Google Calendar. Per il live entrambe devono essere `false`. `MOCK_CALENDAR=true` consente invece un calendario locale mentre la telefonia è reale; in questo caso non viene creato alcun evento Google.

Il mock registra le azioni nel database, non simula audio né pianifica webhook in background. Per completare il flusso si possono invocare i tool come nell'esempio sotto, o eseguire i test automatici.

## Prova completa senza credenziali

```bash
pytest -q
```

I test creano un database temporaneo separato: audit → outreach → demo → WhatsApp mock → disponibilità → prenotazione → webhook finale. Verificano anche autenticazione, escaping HTML, replay, conflitti calendario e payload outbound.

Per una prova manuale, copia `id` da `GET /api/prospects` (Basic Auth) e il `conversation_id` dalla risposta demo:

```bash
curl -u admin:local-development-password http://localhost:8000/api/prospects
curl -X POST http://localhost:8000/api/tools/check-calendar \
  -H 'X-Tool-Key: local-development-tool-key'
# Sostituisci PROSPECT_ID e SLOT_ISO con valori restituiti dal servizio.
curl -X POST http://localhost:8000/api/tools/book-sales-meeting \
  -H 'X-Tool-Key: local-development-tool-key' -H 'Content-Type: application/json' \
  -d '{"prospect_id":"PROSPECT_ID","preferred_slot":"SLOT_ISO"}'
curl -X POST http://localhost:8000/api/tools/post-call-webhook \
  -H 'X-Tool-Key: local-development-tool-key' -H 'Content-Type: application/json' \
  -d '{"type":"post_call_transcription","data":{"conversation_id":"CONVERSATION_ID","transcript":[],"metadata":{"call_duration_secs":90},"analysis":{"call_successful":"success"}}}'
```

La risposta mock di WhatsApp è `mock_sent`. La dashboard mostra lo stato aggiornato al ricaricamento. Una demo completata può ricevere un nuovo invito dalla dashboard; il precedente token viene invalidato. La prenotazione esistente resta associata al prospect: ripetere una demo non cancella un evento.

## Import CSV e audit batch

Intestazione CSV:

```csv
company_name,owner_name,city,service_type,landline_phone,mobile_phone
Rossi Serramenti,Marco,Brescia,Sostituzione infissi,+390300000001,+393330000001
```

```bash
python -m scripts.import_prospects prospects.csv
python -m scripts.run_audit_batch --limit 10 --interval 5
```

L'import segnala righe non valide e numeri duplicati senza stampare i dati personali. Il batch usa il server autenticato, lavora solo sui prospect `pending` e attende tra le richieste. Non lanciare campagne live senza aver prima controllato destinatari e configurazione.

## Attivazione Twilio e ElevenLabs

1. Genera tre segreti distinti di almeno 24 caratteri per `ADMIN_PASSWORD`, `SECRET_KEY`, `TOOL_API_KEY` (`python -c 'import secrets; print(secrets.token_urlsafe(32))'`). Fallo anche prima di esporre un ambiente mock in rete. Non caricare `.env` o credenziali nel repository.
2. Avvia `ngrok http 8000`. Imposta l'URL HTTPS risultante in `PUBLIC_BASE_URL` e riavvia FastAPI. Il valore deve corrispondere esattamente all'origine pubblica, senza percorso finale. Cambiarlo richiede nuovi link e nuove configurazioni webhook. Non fidarti di header forwarded arbitrari.
3. Inserisci `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` e `TWILIO_WHATSAPP_FROM` (`whatsapp:+...`). Usa un numero abilitato per le destinazioni desiderate. Il callback audit viene impostato per ciascuna chiamata dal codice.
4. In Twilio configura l'inbound WhatsApp come POST a `PUBLIC_BASE_URL/api/demo/whatsapp`. Un messaggio `PROVA` da un cellulare già associato a un prospect richiede la demo sullo stesso numero. Mittenti sconosciuti o messaggi diversi vengono ignorati. In sandbox il destinatario deve aver aderito alla sandbox.
5. In ElevenLabs crea un agente italiano e importa/collega il numero Twilio. Copia `ELEVENLABS_AGENT_ID` e **l'ID del numero importato in ElevenLabs** in `ELEVENLABS_PHONE_NUMBER_ID` (non il numero E.164 e non il SID Twilio).
6. Copia First Message e System Prompt da `prompts/elevenlabs_dual_persona.md`. Scegli una voce/modello disponibili nel tuo account e prova le interruzioni. I tempi di circa 60+30 secondi sono obiettivi di conversazione, non una garanzia di latenza.
7. Crea in ElevenLabs un segreto con valore `TOOL_API_KEY`; usa il suo ID nei tre payload di `prompts/server_tools.json`, sostituisci l'host, crea i tool e collegali all'agente. I tool usano `X-Tool-Key`. Il `prospect_id` arriva dalle variabili dinamiche outbound.
8. Imposta il webhook post-call `post_call_transcription` a `PUBLIC_BASE_URL/api/tools/post-call-webhook`, abilita i retry e copia il segreto generato in `ELEVENLABS_WEBHOOK_SECRET`. Il backend verifica HMAC SHA-256 (`t=...,v0=...`) sul corpo originale con tolleranza di cinque minuti. Eventi audio e altri tipi vengono ignorati.
9. Configura il calendario, poi imposta `DRY_RUN=false` e `MOCK_MODE=false`. Riavvia. Il server rifiuta configurazioni live incomplete o con segreti locali di default. Prova prima sul tuo numero.

Il payload outbound usa `POST https://api.elevenlabs.io/v1/convai/twilio/outbound-call`, header `xi-api-key`, `agent_id`, `agent_phone_number_id`, `to_number` e `conversation_initiation_client_data.dynamic_variables`. Variabili: `prospect_id`, `company_name`, `owner_name`, `city`, `service_type`, `audit_time`.

Il ring audit imposta `timeout=18`, senza registrazione. Se la chiamata viene connessa, riproduce un breve messaggio cortese e termina. `completed` significa connessione (anche IVR/segreteria), **non** prova che abbia risposto una persona. `no-answer` e `busy` generano messaggi diversi. Il testo non inventa cinque squilli e non promette costi zero. `audit_timestamp` è l'avvio della richiesta; `audit_ring_duration` è calcolato solo quando disponibili eventi sufficienti, non da `CallDuration`, che misura la durata chiamata.

WhatsApp: il servizio usa messaggi liberi, adatti a una conversazione aperta dal destinatario. Per messaggi business fuori dalla finestra consentita dal provider occorrono template approvati, non implementati qui. Se l'invio fallisce, l'evento calendario resta confermato e il tool espone lo stato della notifica senza dichiarare falsamente la consegna. L'outreach iniziale viene soltanto generato e aperto manualmente con `wa.me`; non parte in automatico.

## Google Calendar

Abilita Calendar API nel progetto Google Cloud. Due opzioni:

- **Service account:** crea la chiave JSON fuori dal repository, condividi un calendario dedicato con l'email del service account concedendo modifica degli eventi; imposta `GOOGLE_SERVICE_ACCOUNT_FILE` e `GOOGLE_CALENDAR_ID`. Gli inviti email non vengono inviati con questa modalità: l'email è conservata nella descrizione dell'evento e il riepilogo può essere inviato via WhatsApp.
- **OAuth:** crea un file authorized-user con `refresh_token`, `client_id` e `client_secret` ottenuto tramite il consenso Google con scope `https://www.googleapis.com/auth/calendar`; imposta `GOOGLE_OAUTH_FILE` e `GOOGLE_CALENDAR_ID`. Se presente l'email del prospect, viene aggiunta come attendee con `sendUpdates=all`.

Imposta `MOCK_CALENDAR=false` per usare Google. Gli slot sono di dieci minuti (configurabili), nei giorni lavorativi, fra le 09:00 e le 18:00 nel fuso `TIMEZONE`, almeno trenta minuti nel futuro e nei prossimi quindici giorni. Vengono controllati gli eventi occupati di Google e le prenotazioni locali. Il tool restituisce due ISO timestamp con offset e una frase parlabile; accetta prenotazioni solo su questa griglia. Non interpreta date libere ambigue.

Una prenotazione viene riservata nel DB prima dell'inserimento esterno; l'ID Google deterministico permette di riconciliare una risposta persa ripetendo **lo stesso** slot. Non vengono generati link Meet automaticamente. Per una videochiamata, aggiungi il link all'evento o estendi l'integrazione Calendar.

## Endpoint

| Endpoint | Autenticazione | Funzione |
|---|---|---|
| `GET /health` | Pubblico | Stato processo e modalità |
| `GET /admin/prospects` | Basic Auth | Dashboard |
| `GET/POST /api/prospects` | Basic Auth | Elenco paginato / creazione |
| `GET /api/prospects/{id}/invite` | Basic Auth | Link demo firmato |
| `POST /api/prospects/{id}/reset-demo` | Basic Auth | Nuovo invito dopo demo completata |
| `GET /api/prospects/{id}/history` | Basic Auth | Log, trascrizioni e appuntamenti |
| `POST /api/audit/{id}/start` | Basic Auth | Avvia audit una sola volta |
| `POST /api/audit/twilio-status-callback?attempt=...` | Firma Twilio | Esito audit |
| `GET /prova/{id}?token=...` | Token firmato | Landing personale, nessuna chiamata al GET |
| `POST /api/demo/trigger` | Token nel JSON + conferma | Richiesta demo |
| `POST /api/demo/whatsapp` | Firma Twilio | Trigger `PROVA` |
| `POST /api/tools/send-whatsapp-simulation` | X-Tool-Key | WhatsApp dimostrativo |
| `POST /api/tools/check-calendar` | X-Tool-Key | Due disponibilità |
| `POST /api/tools/book-sales-meeting` | X-Tool-Key | Prenotazione |
| `POST /api/tools/post-call-webhook` | HMAC ElevenLabs | Trascrizione, durata, analisi |

In mock i callback Twilio e ElevenLabs richiedono `X-Tool-Key` al posto della firma provider. Basic Auth e i tool restano protetti anche in mock. Nessun CORS cross-origin è abilitato; l'interfaccia usa la stessa origine.

## Deploy e limiti operativi dell'MVP

```bash
docker build -t caller-genius .
docker run --env-file .env -p 8000:8000 \
  -e DATABASE_URL=sqlite+aiosqlite:////data/voice_funnel.db \
  -v caller-genius-data:/data caller-genius
```

Per Google monta anche il file credenziali in sola lettura e configura il relativo percorso nel container. Usa HTTPS tramite reverse proxy. In produzione configura limiti richieste/corpo e rate limiting sul proxy, proteggi l'accesso amministrativo e conserva backup del volume. Gli access log applicativi sono disattivati per evitare di registrare token nei link; configura la stessa redazione sul proxy.

PostgreSQL: `DATABASE_URL=postgresql+asyncpg://user:password@host/database` (anche `postgresql://` viene normalizzato). La versione iniziale crea lo schema con `create_all`: i successivi cambiamenti di schema richiedono migrazioni esplicite, non vengono applicati automaticamente. SQLite è adatto al pilot a basso traffico. Avvia un worker; i claim demo e i vincoli sugli slot sono persistenti, ma la coordinazione delle notifiche di prenotazione è locale al processo.

Le chiamate esterne non vengono ritentate automaticamente. Uno stato `starting`/`unknown` dopo timeout o riavvio richiede controllo nel provider: non riportarlo a `ready` senza aver verificato che la chiamata non sia stata accettata. Per riconciliare un audit usa il callback firmato con attempt e SID corretti. Per una demo incerta confronta i log ElevenLabs e aggiorna il record soltanto dopo verifica. Non è presente una coda durevole né un pannello di riconciliazione automatica. Le prenotazioni `pending` bloccano lo slot finché riconciliate; ripetere lo stesso booking recupera un evento già creato. Gli eventi modificati/cancellati direttamente su Google non vengono sincronizzati nel DB. Google Calendar non offre un vincolo atomico anti-sovrapposizione rispetto a scritture esterne: usa un calendario dedicato e controlla i conflitti manuali.

I link firmati sono credenziali temporanee, scadono dopo sette giorni e devono essere condivisi solo con il destinatario. Il modulo conferma il numero ma non verifica il possesso con OTP. Per un servizio pubblico a larga scala aggiungere verifica numero, rate limiting, coda/reconciliation, retention/cancellazione dei dati e migrazioni. Il codice è pronto per test e pilot controllato; telefonia, consegna WhatsApp e Google vanno collaudati con i tuoi account prima dell'uso operativo. Trascrizioni e dati personali vengono salvati: limita accesso e conservazione in base al tuo utilizzo.

## Fonti tecniche

- [ElevenLabs outbound Twilio](https://elevenlabs.io/docs/api-reference/integrations/twilio/outbound-call)
- [ElevenLabs webhook tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools)
- [ElevenLabs post-call webhooks](https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks)
- [Twilio Call resource](https://www.twilio.com/docs/voice/api/call-resource)
- [Google FreeBusy](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query)
- [Google events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)
