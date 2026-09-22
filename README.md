# zotero-llm-bridge (`zlb`)

CLI locale per Zotero 10, utilizzabile da terminale, script e altri LLM su Linux, macOS e Windows. Il comando breve è `zlb`. Usa `http://localhost:23119/api/` con Zotero aperto. Tutte le scritture passano dall'API locale; non modifica i database SQLite e non usa zotero.org.

## Avvertenza e responsabilità

`zlb` può modificare raccolte e schede e copiare PDF nella libreria Zotero. L'utilizzatore deve leggere il codice, controllare i comandi proposti anche da un LLM, verificare i risultati e mantenere un backup della libreria. Deve inoltre verificare identità, metadati e diritti d'uso dei documenti importati. Il programma è fornito **«così com'è»**, senza garanzie di correttezza, idoneità o assenza di errori. Nei limiti consentiti dalla legge applicabile, autori e contributori declinano responsabilità per perdite di dati, errori bibliografici o altri danni derivanti dall'uso del programma.

## Licenza

Il codice è distribuito con licenza [0BSD](LICENSE): si può usare, copiare, modificare e ridistribuire per qualunque scopo, anche commerciale, senza obbligo di attribuzione. La licenza include l'esclusione di garanzie e responsabilità nel suo testo originale.

## Installazione

Servono Zotero 10 aperto, l'opzione **Settings → Advanced → Allow other applications on this computer to communicate with Zotero** attiva e Python 3.10 o successivo. Non serve installare un'estensione `.xpi` né creare una chiave su zotero.org. Questo repository è privato: il clone richiede accesso GitHub.

### Linux e macOS

```bash
gh repo clone paolovolterra/zotero-llm-bridge
cd zotero-llm-bridge
python3 --version
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/zlb" "$HOME/.local/bin/zlb"
export PATH="$HOME/.local/bin:$PATH"
zlb status
```

Se `gh` non è installato, clonare con `git clone https://github.com/paolovolterra/zotero-llm-bridge.git` usando le proprie credenziali GitHub. Il collegamento in `~/.local/bin` si crea una sola volta; per aggiornare il programma basta `git pull` nella cartella clonata. Rendere persistente l'aggiunta al `PATH` nel profilo della propria shell, se non è già configurata.

### Windows

```powershell
gh repo clone paolovolterra/zotero-llm-bridge
cd zotero-llm-bridge
py -3 --version
py -3 -m pip install --user .
zlb status
```

Se `zlb` non è riconosciuto, aggiungere al `PATH` la directory `Scripts` dell'installazione Python dell'utente. In alternativa, dalla cartella del repository si può sempre eseguire `py -3 PY\zotero_llm_bridge.py status`.

## Modello d'uso

Un LLM può cercare fonti sul web, preparare un manifest e invocare i comandi del CLI. Chi utilizza il pacchetto può leggere il codice e decide quali operazioni autorizzare ed eseguire sulla propria libreria. Il CLI usa le richieste e l'autorizzazione dell'API locale di Zotero: è Zotero a creare le chiavi, registrare le schede e gestire i file importati. I controlli del CLI verificano appartenenza alla raccolta e integrità dei PDF, ma non accertano da soli che un documento sia il paper citato o che i suoi metadati siano corretti.

## Avvio

```bash
./zlb status
./zlb collections --parent "My papers"
./zlb collections "My papers"
./zlb "My papers" --top --limit 20
```

`zlb collections "My papers"` elenca le sottoraccolte; `zlb "My papers"` elenca schede e allegati nella raccolta. Aggiungere `--top` per vedere solo le schede principali. La forma breve equivale a `zlb search --collection "My papers"`. Il nome deve essere esatto e univoco; se non lo è, usare la chiave a otto caratteri.

### Esempio reale: `PolicyIA`

```bash
zlb -h
zlb collections PolicyIA
zlb PolicyIA --top --limit 5
zlb search --collection PolicyIA --tag AI --top --limit 20
zlb bib --collection PolicyIA
zlb bib --collection PolicyIA --output PolicyIA.bib
```

`zlb collections PolicyIA` mostra le **sottoraccolte**: nella prova del 22 settembre ha restituito `[]`. `zlb PolicyIA --top --limit 5` mostra le prime cinque dei 53 item principali osservati. `zlb bib --collection PolicyIA` stampa il BibTeX della raccolta sul terminale; con `--output` lo salva nella directory corrente. L'esportazione diretta usa il traduttore BibTeX di Zotero per le schede bibliografiche, include i PDF autonomi come voci `misc` e aggiunge `key8`. Le note autonome vengono saltate e riportate nel riepilogo JSON quando si usa `--output`. Non serve un manifest per questi comandi.

L'export rispecchia i metadati presenti in Zotero: se mancano autori, date o sede editoriale, il `.bib` può produrre avvisi durante la compilazione. La correzione dei metadati si fa in Zotero e poi si ripete l'esportazione. L'[API ufficiale supporta BibTeX come formato di export](https://www.zotero.org/support/dev/web_api/v3/basics).

I comandi restituiscono JSON. Le letture non richiedono autorizzazione; le scritture seguono la procedura qui sotto.

### Autorizzazione delle scritture

Alla prima operazione che modifica Zotero (`ensure-collection`, `add`, `move`, `upload` o `apply`), il client aperto mostra una richiesta per **ZoteroLLMBridge**:

- **Allow** autorizza una sola scrittura. Un'operazione composta da più scritture, come l'upload di un PDF, può richiedere altre conferme.
- **Always Allow** restituisce una chiave riutilizzabile. `zlb` la salva localmente e le scritture successive non mostrano un nuovo prompt finché l'autorizzazione resta valida.
- **Deny** rifiuta l'operazione; `zlb` non salva alcuna chiave.

La cache predefinita è `~/.config/zotero_llm_bridge/auth.json` su Linux/macOS oppure `%APPDATA%\\zotero_llm_bridge\\auth.json` su Windows. Si può scegliere un altro file con `ZOTERO_LLM_BRIDGE_AUTH_FILE`. La cache contiene la chiave e l'identificativo dell'istanza Zotero, non le credenziali di zotero.org; su Linux/macOS il file è creato con permessi `0600`. La copia di lavoro condivisa usa invece `.zotero-local-auth.json` nella cartella del pacchetto, esclusa da Git. Una chiave associata a un'altra istanza non viene riusata. Se Zotero rifiuta una chiave salvata (`401`), il CLI la elimina e richiede una nuova autorizzazione.

`zlb status` mostra `remembered_authorization: true` quando trova una cache per l'istanza corrente; questo indica la presenza della chiave, non ne prova ancora la validità. Si possono revocare le autorizzazioni ricordate in Zotero: **Settings → Advanced → Clear Write Authorizations**. La chiave non va copiata in un repository o condivisa con altri utenti. La [documentazione ufficiale dell'API locale](https://www.zotero.org/support/dev/web_api/v3/local_api) descrive il prompt e la revoca.

## Ricerca

```bash
./zlb search --collection "My papers" --q "credit risk"
./zlb search --tag QEF --item-type=-attachment --top --limit 20
./zlb search --tag "QEF || AI" --q "default" --qmode everything
./zlb search --tag QEF --tag PMI --start 20 --limit 20
```

`--collection` accetta la chiave a otto caratteri o un nome esatto e univoco. Filtri diversi si combinano; più `--tag` richiedono tutti i tag (AND). Nelle espressioni di tag e tipo item, `||` significa OR e il prefisso `-` esclude un valore. `--q` è la ricerca testuale di Zotero, che tratta la stringa come frase; non interpreta operatori booleani generici. `--qmode everything` estende la ricerca al testo integrale indicizzato. I risultati sono paginati con `--start` e `--limit` (massimo 100 per pagina). `--top` esclude gli allegati figli.

### Ricerca semantica su molti PDF

Per domande sul contenuto dei paper, è consigliato un indice semantico separato: estrarre il testo degli allegati Zotero, dividerlo in chunk con pagina o posizione, calcolare gli embedding e ingerirli in shard FAISS. Una mappa persistente deve collegare ogni chunk alla chiave dell'allegato, alla scheda madre, al percorso del PDF e alla posizione nel documento. Conservare anche un hash del file per aggiornare o invalidare i chunk quando il PDF cambia.

Il flusso di ricerca può combinare i due livelli: prima restringere per raccolta, tag, tipo e metadati tramite API Zotero; poi cercare semanticamente nei chunk degli allegati selezionati e riportare sempre il passo, la pagina e la scheda originale. Il risultato semantico è una pista da verificare sul PDF, non un metadato Zotero. `ZoteroLLMBridge` espone oggi il livello API; non costruisce né interroga gli shard FAISS. Se esiste già un corpus indicizzato, riusarlo prima di crearne un altro.

## Raccolte e schede esistenti

```bash
./zlb ensure-collection --parent "My papers" --name "New collection"
./zlb add --collection "New collection" ABCD1234
./zlb move --source "My papers" --target "New collection" ABCD1234
```

`add` conserva le altre appartenenze. `move` toglie la scheda dalla raccolta sorgente e la aggiunge alla destinazione. La chiave può riferirsi anche a un allegato: il comando risale alla scheda madre. Le operazioni sono idempotenti e verificano il risultato via API.

## PDF

```bash
./zlb upload --file /path/to/article.pdf --collection "New collection" --title "Article title"
./zlb upload --file /path/to/article.pdf --collection "New collection" --parent-item ABCD1234
```

Il PDF originale resta sul disco. Prima di creare un allegato, `upload` controlla l'MD5 degli allegati PDF **nell'intera libreria** tramite un indice locale ricavato dall'API Zotero e conferma il candidato confrontando SHA-256 con il file nello storage. Se il PDF esiste già, aggiunge la scheda alla raccolta richiesta e restituisce `already_present` o `added_existing_pdf`, senza duplicare il file né cambiare titolo o tag. Se è indicato `--parent-item` ma la copia identica appartiene a un'altra scheda, si ferma e segnala le due chiavi. La prima costruzione dell'indice può richiedere alcuni minuti in una libreria grande; dopo, il CLI usa la versione della libreria per aggiornare solo gli allegati modificati. La cache `.zlb-attachment-index.json` resta locale ed è esclusa da Git.

Il limite di upload è 100 MB per file. Zotero assegna le chiavi a otto caratteri. `zlb` non avvia né corregge i metadati: il loro recupero e controllo si svolgono direttamente in Zotero.

### Se qualcosa è già presente

- `ensure-collection` riusa la raccolta con lo stesso nome sotto lo stesso padre e restituisce `created: false`; se il nome è ambiguo, chiede una chiave a otto caratteri.
- `add` non duplica l'appartenenza. `move` restituisce `changed: 0` se la scheda è già nella destinazione e non è più nella sorgente. Nessuno dei due comandi modifica i tag.
- `upload` riusa un PDF identico già presente in libreria. I `--tag` sono applicati solo quando viene creato un nuovo allegato; non aggiornano una scheda preesistente.
- `apply` cerca prima la scheda per chiave, DOI o titolo e aggiunge alla raccolta quella con PDF già disponibile. Le corrispondenze bibliografiche ambigue richiedono verifica; il CLI non corregge i metadati.

## Riferimenti e BibTeX

Manifest JSON di esempio:

```json
{
  "source": {"title": "Paper di origine"},
  "references": [
    {"id": "1", "citekey": "rossi2025", "type": "article", "title": "Titolo", "author": "Rossi, Mario", "year": "2025", "doi": "10.1234/example", "zotero_key": "ABCD1234"},
    {"id": "2", "citekey": "bianchi2024", "title": "Altro titolo", "pdf_path": "/path/to/another.pdf"},
    {"id": "3", "citekey": "verdi2023", "title": "Terzo titolo", "pdf_url": "https://example.org/paper.pdf"}
  ]
}
```

```bash
./zlb apply --manifest /path/to/references.json --collection "New collection" --output /path/to/references.bib
./zlb bib --manifest /path/to/references.json --collection "New collection" --output /path/to/references.bib
```

`apply` cerca per chiave Zotero, DOI o titolo nell'intera libreria; aggiunge le schede già presenti e importa PDF locali o da URL HTTPS. Aggiorna il manifest dopo ogni importazione riuscita, così può riprendere dopo un'interruzione. `bib` **con manifest** richiede `--output`, mette le voci senza PDF all'inizio e scrive `key8` e percorso per quelle risolte. `bib` **senza manifest** esporta direttamente la raccolta con i metadati correnti di Zotero. Il CLI controlla la presenza del PDF, non l'identità scientifica di un URL: verificare fonte, titolo, autori, anno e DOI prima di associare il PDF e pubblicare il BibTeX.

## Per altri LLM

Fornire questa guida e il comando `zlb` disponibile nel `PATH`, oppure il suo percorso assoluto. Il CLI richiede Python 3.10+ e la libreria standard. Su Linux e macOS si può usare il wrapper Bash `zlb`; su Windows si può eseguire `py -3 PY\\zotero_llm_bridge.py --help` dalla cartella del pacchetto. `pyproject.toml` offre un entry point installabile `zlb` su tutte le piattaforme. `zlb --help` mostra tutti gli argomenti.

## Sviluppo

```bash
python3 -m unittest discover -s tests -v
```

I test non richiedono Zotero e coprono il riuso di un PDF già presente in libreria e l'ordine delle voci nel BibTeX. Prima di una pubblicazione pubblica occorre scegliere una licenza e verificare il pacchetto sulle piattaforme dichiarate; finora è stato eseguito dal vivo solo su Linux.

Esempi basati su un caso d'uso reale sono in `examples/uso_20260922.md`.
