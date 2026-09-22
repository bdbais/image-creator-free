// Mostra l'ultima versione pubblicata su GitHub, se la chiamata riesce.
(function () {
  var node = document.getElementById("version");
  if (!node) return;
  fetch("https://api.github.com/repos/bdbais/image-creator-free/releases/latest")
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (data) {
      var tag = (data.tag_name || "").replace(/^v/, "");
      if (!tag) return;
      var date = data.published_at
        ? new Date(data.published_at).toLocaleDateString("it-IT",
            { day: "numeric", month: "long", year: "numeric" })
        : "";
      node.textContent = "Versione " + tag + (date ? " · " + date : "");
      node.hidden = false;
    })
    .catch(function () { /* nessuna rete: la riga resta nascosta */ });
})();
