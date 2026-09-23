# Manuale di Image Creator Free

## Il primo avvio

Alla prima apertura il programma chiede due cose:

1. **Dove tenere il modello.** Sono circa 33 GB: propone il disco interno con più
   spazio, ma puoi indicarne un altro. La cartella si cambia anche dopo, da
   *File → Impostazioni*.
2. **Il permesso a installare l'ambiente di calcolo** (PyTorch, diffusers,
   transformers: circa 3 GB) in `%LOCALAPPDATA%\ImageCreatorFree\runtime`. È una
   cartella a parte: il Python che hai già sul computer non viene toccato, e per
   disinstallare tutto basta cancellarla.

Il modello vero e proprio si scarica alla prima generazione. Durante il download la
barra di stato mostra la percentuale; *Modello → Mostra il registro* (Ctrl+L) apre
il dettaglio riga per riga.

## Scrivere un prompt per Qwen-Image-2.1

Questo modello è nato per la tipografia e per le scene descritte per esteso. Tre
abitudini che cambiano il risultato:

- **Metti tra virgolette le parole che devono comparire nell'immagine.**
  `A neon shop sign that reads "QWEN IMAGE 2.1"` scrive davvero quella frase.
- **Descrivi la luce, il materiale e l'inquadratura**, non solo il soggetto:
  "luce radente del mattino, lino, grana fotografica, medio formato".
- **Di' anche cosa non vuoi**, nel campo *Prompt negativo* della scheda Avanzate.

I quaranta esempi ufficiali nella colonna di sinistra sono un buon punto di
partenza: doppio clic per caricarne uno, poi modificalo.

## Immagini trasparenti

Chiedi esplicitamente il canale alpha, con la formula consigliata da Qwen:

> This is an RGBA image with transparency. ... The image has alpha channel and the
> background is transparent.

Il PNG salvato mantiene la trasparenza.

## Modificare le proprie immagini

Nella scheda *Immagini di riferimento* trascina da una a dieci immagini, poi
citale nel prompt nell'ordine in cui le hai messe: *image 1*, *image 2*...
Funziona per cambiare uno sfondo, montare una foto di gruppo da più ritratti,
arredare una stanza con oggetti fotografati da te. Quando ci sono riferimenti, il
formato e la risoluzione li decide l'immagine di partenza.

## Progetti

Ogni generazione appartiene a un progetto. Se non ne hai aperto uno, il primo clic su
*Genera* lo crea con le prime parole del prompt; lo trovi nella scheda *Progetti*.

Un progetto ricorda prompt, prompt negativo, formato, qualità, passi, aderenza, seed,
numero di immagini e immagini di riferimento, che vengono copiate nella sua cartella
(`immagini\<progetto>\riferimenti`), così rigenerare funziona anche se sposti gli
originali. Ogni immagine conserva i parametri con cui è nata.

- **Duplica** (Ctrl+D): nuovo progetto con gli stessi parametri e nessuna immagine.
  Cambia quello che vuoi e premi *Genera*: l'originale resta com'è.
- **Nuovo progetto da questa immagine**: parte dall'immagine selezionata in galleria,
  seed compreso, per fare varianti di un risultato riuscito.
- **Elimina** toglie il progetto dall'elenco; le immagini restano su disco, a meno che
  tu non scelga di cancellarle.
- *Tutte le immagini*, in cima all'elenco, mostra le ultime generate da qualunque progetto.

## Restaurare foto antiche

Negli *Esempi*, gruppo *Restauro foto*. La prima immagine di riferimento è la foto da
restaurare; le altre sono foto della **stessa persona**, usate solo per ricostruire il
volto dove l'originale è rovinato, sfocato o mancante. Più sono simili per età e
angolazione, meglio funziona. Si può restaurare restando in bianco e nero o colorare.

## Qualità, formati e memoria

| Livello | Risoluzione (1:1) | Passi |
|---|---|---|
| Bozza | 1024x1024 | 20 |
| Standard | 1536x1536 | 30 |
| Alta | 2048x2048 | 40 |

La *Alta* corrisponde ai valori della scheda ufficiale del modello.

Il modello pesa 33 GB in bf16 e il suo pezzo più grande — il codificatore di testo —
ne occupa 17,5 da solo. Per questo:

| Modalità | Quando |
|---|---|
| Tutto in VRAM | schede da 40 GB in su |
| Offload dei moduli su CPU | da 20 GB di VRAM |
| Offload sequenziale | da 8 GB: il modello sta in RAM e passa sulla scheda un pezzo alla volta |

In automatico il programma sceglie da sé. Se vedi *VRAM esaurita*, scendi di
qualità o imposta a mano l'offload sequenziale in *File → Impostazioni*.

**Quanto ci vuole.** Misure su una RTX 4070 da 12 GB, modello su SSD, offload
sequenziale, stesso prompt e stesso seed:

| Configurazione | Tempo | Per passo |
|---|---|---|
| Caricamento del modello (da SSD) | 41 s | — |
| 1024x1024, 20 passi | 3 min | 9,1 s |
| 1536x1536, 30 passi (Standard) | 8 min 36 s | 17,2 s |
| 2048x2048, 40 passi (Alta) | VRAM esaurita dopo ~20 min | — |

Il modello resta caricato, quindi le immagini successive partono senza il tempo
di caricamento. Con 12 GB la qualità Alta non è raggiungibile: il programma
avvisa prima di provarci.

**Il disco conta più della scheda video.** Con lo stesso identico modello su un
disco meccanico il caricamento passa da 38 secondi a circa un'ora: i 33 GB
vengono letti per intero a ogni avvio. Tieni il modello su un SSD; il programma
lo propone da sé e avvisa se scegli un disco a piatti.

## Dove finiscono le cose

| Cosa | Dove |
|---|---|
| Immagini | `Immagini\Image Creator Free`, una cartella per progetto (modificabile) |
| Impostazioni, storico e progetti | `%LOCALAPPDATA%\ImageCreatorFree` |
| Ambiente di calcolo | `%LOCALAPPDATA%\ImageCreatorFree\runtime` |
| Modello | la cartella scelta al primo avvio |

Ogni PNG porta dentro di sé prompt, seed, passi e parametri: il pulsante *Riusa i
parametri* li rimette nei campi, così puoi ripartire da un risultato che ti è
piaciuto cambiando una cosa sola.

## Se qualcosa non va

**"Ambiente di generazione non installato"** — *Modello → Reinstalla l'ambiente di
calcolo*.

**VRAM esaurita** — qualità *Bozza*, una sola immagine per volta, oppure offload
sequenziale.

**Il download si interrompe** — riprende da dove era arrivato: rilancia la
generazione. Hugging Face tiene i file a metà nella stessa cartella.

**La generazione sembra bloccata** — al primo avvio il caricamento del modello dal
disco richiede minuti, specie con l'offload sequenziale. Il registro (Ctrl+L) dice
sempre a che punto è.

**Il processo di generazione si chiude da solo durante il caricamento** — la memoria
non basta: il modello passa tutto dalla RAM e chiede circa 35 GB tra RAM e file di
paging. Chiudi emulatori, macchine virtuali e browser pesanti, oppure aumenta il file
di paging su un disco con spazio libero. Il programma avvisa prima di iniziare.

**Windows SmartScreen blocca l'installer** — i file non sono firmati:
*Ulteriori informazioni → Esegui comunque*. Le impronte SHA-256 sono pubblicate
con ogni release.
