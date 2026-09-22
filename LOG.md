# ZoteroLLMBridge — Log

## 2026-09-22

- Estratte in un CLI riutilizzabile le operazioni Zotero locali già sperimentate: raccolte, appartenenze, import PDF e BibTeX da manifest.
- Verificati sintassi, connessione a Zotero 10.0.3 e generazione BibTeX su una raccolta di prova (una voce con PDF, una mancante); nessuna nuova scrittura sulla libreria per il test.
- Resa portabile la sorgente Python per Linux, macOS e Windows; wrapper Bash per Linux/macOS, avvio Python diretto o entry point installato per Windows. `apply` cerca i riferimenti già presenti nell'intera libreria prima dell'importazione.
- Sostituita la scansione completa della libreria, troppo lenta, con query mirate per DOI e titolo sull'API locale. Aggiunti due test unitari senza Zotero; verificato dal vivo `apply` su una scheda già presente, senza modifica alla libreria.
- Esplicitato nel README il modello d'uso con LLM: l'utilizzatore decide ed esegue le operazioni sulla propria libreria; il CLI usa l'API locale di Zotero e verifica i file, mentre la validazione bibliografica richiede controllo del documento.
- Aggiunto `search` per raccolta, tag, testo e tipo di item, con filtri booleani Zotero per tag/tipo e paginazione. Rinominate sorgente, comando e pacchetto in `ZoteroLLMBridge`; aggiunti esempi del lavoro su QEF e FSFDLLM.
- Verificata dal vivo la ricerca usando il nome umano esatto `FSFDLLM references`; aggiornati gli esempi per preferire il nome leggibile quando univoco.
- Documentata la ricerca semantica consigliata: estrazione e chunking degli allegati, ingestione in shard FAISS, mappa chunk→chiavi Zotero/percorso/pagina e uso congiunto dei filtri API. L'indice semantico non è implementato nel CLI.
- Scelto `zlb` come comando breve e `zotero-llm-bridge` come nome del progetto. Preparato il pacchetto per un repository Git autonomo.
- Documentati prompt di autorizzazione Zotero, scelte Allow/Always Allow/Deny, cache locale della chiave, rinnovo su `401`, revoca e significato limitato di `status`.
- Reso `move` idempotente quando la scheda è già nella destinazione. Prima dell'upload, confronto globale dei PDF tramite indice MD5 costruito con l'API locale e verifica SHA-256 del file trovato; cache aggiornata per versione della libreria. I metadati restano gestiti nel client Zotero.
- Aggiunte le scorciatoie richieste dall'uso reale: `zlb NOME_RACCOLTA` cerca gli item e `zlb collections NOME_RACCOLTA` elenca le sottoraccolte. Conservati i flag espliciti per script.
- Aggiunto `zlb bib --collection NOME` senza manifest: esporta tramite il traduttore BibTeX di Zotero, aggiunge `key8` a ogni voce e stampa su stdout o salva con `--output`. Documentati nella guida tutti i comandi provati dall'utente con `PolicyIA`.
- La prova su `PolicyIA` ha rilevato PDF autonomi che il traduttore BibTeX di Zotero non esporta da soli. Aggiunto un fallback `misc` con file e `key8`; le note autonome sono saltate e segnalate nel riepilogo.
- Esportate dal vivo 53 voci di `PolicyIA`, tutte con `key8`; BibTeX ha letto il file senza errori, con avvisi per metadati già mancanti in Zotero.
- Il pacchetto è stato spostato in un repository GitHub privato autonomo `paolovolterra/zotero-llm-bridge`; il repository condiviso `0000` non ne traccia più i file. Documentata l'installazione nel `PATH` via symlink o entry point Python.
- Riscritta la sezione Installazione dal clone del repository alla verifica di `zlb status`, con prerequisiti Zotero/Python e istruzioni separate per Linux/macOS e Windows.
- Inserita in apertura del README un'avvertenza su modifiche alla libreria, verifica dei comandi e dei documenti, backup, assenza di garanzie e limitazione di responsabilità nei limiti della legge applicabile. La licenza resta da scegliere prima di un rilascio pubblico.
- Scelta la licenza 0BSD su richiesta dell'utente per la massima libertà d'uso senza obbligo di attribuzione; aggiunto `LICENSE` e aggiornato il README.
- Portato in apertura del README il flusso guidato da un LLM: ricerca sul web, riuso dei PDF Zotero, import nella raccolta e BibTeX con i riferimenti irrisolti in testa. Esplicitati gli errori dei server esterni e il caso in cui Zotero locale non risponde; rimossa la vecchia nota che diceva di scegliere ancora una licenza.
- Formalizzata la regola che zlb non cancella schede, raccolte o allegati: documentata la cancellazione manuale in Zotero, bloccate le richieste API `DELETE` nel client e aggiunto un test dedicato. `move` modifica soltanto l'appartenenza alle raccolte.
- Avviata la preparazione di un deposito software Zenodo: aggiunte istruzioni d'installazione da archivio ZIP, indipendenti dall'accesso al repository GitHub privato. La pubblicazione richiede ancora revisione dell'archivio e dei metadati.
- Aggiunto al README uno schema Mermaid del flusso LLM → manifest → zlb → Zotero/BibTeX, con ramo per PDF già presenti, nuovi import e fonti irrisolte. Mermaid è supportato nativamente da GitHub e può essere renderizzato da Kroki.
- Su richiesta dell'utente, preparato il passaggio del repository GitHub a visibilità pubblica: revisionati i file tracciati, confermata l'esclusione delle cache locali, aggiornate le istruzioni di installazione che indicavano ancora un repository privato.
