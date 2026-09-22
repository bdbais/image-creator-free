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

**Quanto ci vuole.** Misure fatte su una RTX 4070 da 12 GB con il modello su
SSD, in offload sequenziale: caricamento del modello 38 secondi, poi 6,5 secondi
per passo a 1024x1024, cioè circa due minuti per una immagine da 20 passi. Il
modello resta caricato, quindi le immagini successive partono subito.

**Il disco conta più della scheda video.** Con lo stesso identico modello su un
disco meccanico il caricamento passa da 38 secondi a circa un'ora: i 33 GB
vengono letti per intero a ogni avvio. Tieni il modello su un SSD; il programma
lo propone da sé e avvisa se scegli un disco a piatti.

## Dove finiscono le cose

| Cosa | Dove |
|---|---|
| Immagini | `Immagini\Image Creator Free` (modificabile) |
| Impostazioni e storico | `%LOCALAPPDATA%\ImageCreatorFree` |
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

**Windows SmartScreen blocca l'installer** — i file non sono firmati:
*Ulteriori informazioni → Esegui comunque*. Le impronte SHA-256 sono pubblicate
con ogni release.
