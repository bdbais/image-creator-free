# Sito di Image Creator Free

Sito statico servito da Cloudflare Workers su https://imagecreator.bais.info

```bash
npx wrangler deploy      # pubblica
npx wrangler dev         # anteprima locale
```

`public/index.html` e' un file unico con lo stile incorporato: nessun passo di build.
`public/version.js` legge l'ultima release da GitHub. `public/_headers` contiene la CSP.
