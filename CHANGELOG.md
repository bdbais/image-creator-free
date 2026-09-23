# Changelog

## 1.1.1 - 2026-09-23

- Colorazione di foto in bianco e nero, tra gli esempi di restauro: con colori
  automatici, con i colori che scegli tu (occhi, capelli, abiti, sfondo) o presi
  da una foto a colori della stessa persona.
- Nell'elenco dei progetti le miniature sono allineate anche quando le immagini
  hanno proporzioni diverse.

## 1.1.0 - 2026-09-23

- Progetti: ogni progetto ricorda prompt, parametri, immagini di riferimento e
  risultati, in una sua cartella. Si duplica per rigenerare con parametri
  diversi senza toccare l'originale, o si parte da una singola immagine con il
  suo seed.
- Esempi: "I tuoi prompt" con quelli già usati, scene complesse e restauro di
  foto antiche o rovinate con più immagini della stessa persona.
- Aggiornamento automatico: il programma controlla se c'è una versione nuova,
  mostra le novità e la installa.
- Corretto il crash (0xC0000005) al caricamento del modello quando il
  programma veniva avviato dall'eseguibile.
- Avviso prima di caricare il modello quando RAM e file di paging non bastano.

## 1.0.0 - 2026-09-22

Prima versione.

- Generazione da testo con Qwen-Image-2.1, sette formati e tre livelli di qualità.
- Immagini trasparenti (RGBA) native.
- Modifica di immagini con fino a dieci riferimenti trascinati nella finestra.
- I 40 esempi ufficiali della scheda del modello e della demo Hugging Face.
- Galleria locale con parametri salvati nel PNG e ripresa dei parametri.
- Installazione automatica dell'ambiente di calcolo in una cartella separata,
  senza toccare il Python di sistema.
- Quattro modalità di uso della memoria, da 8 GB di VRAM in su.
