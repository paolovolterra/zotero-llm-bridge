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
