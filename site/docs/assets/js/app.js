(function () {
  'use strict';

  var COULEURS = ['#d9eeea', '#9fd5cd', '#4cb5a9', '#2A9D8F', '#1F3A5F'];
  var LIGNES = ['#7fc8be', '#2A9D8F', '#1F7A8C', '#1F3A5F', '#0d1f36'];
  var LIGNES_MAX = 500;
  var nombre = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 });
  var entier = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
  var etat = { catalogue: null, cache: {}, carte: null, couche: null };

  function $(id) { return document.getElementById(id); }

  function unique(tableau) {
    return tableau.filter(function (v, i) { return tableau.indexOf(v) === i; });
  }

  function echapper(texte) {
    var div = document.createElement('div');
    div.textContent = String(texte);
    return div.innerHTML;
  }

  function message(texte) {
    var zone = $('message');
    zone.textContent = texte || '';
    zone.hidden = !texte;
  }

  function lire(feature, champ) {
    var v = feature.properties[champ];
    if (v === undefined && champ === 'id') { v = feature.id; }
    return v;
  }

  function valeur(feature, champ) {
    var v = lire(feature, champ);
    if (v === null || v === undefined || v === '') { return null; }
    var n = Number(v);
    return isNaN(n) ? null : n;
  }

  function formater(v, type) {
    if (v === null || v === undefined || v === '') { return '–'; }
    if (type === 'texte') { return String(v); }
    var n = Number(v);
    if (isNaN(n)) { return String(v); }
    if (type === 'pourcentage') { return nombre.format(n) + ' %'; }
    if (type === 'entier') { return entier.format(n); }
    return nombre.format(n);
  }

  function colonne(jeu, champ) {
    return jeu.colonnes.filter(function (c) { return c.champ === champ; })[0];
  }

  function libelleIndicateur(jeu, champ) {
    var i = jeu.indicateurs.filter(function (x) { return x.champ === champ; })[0];
    return i ? i.libelle : champ;
  }

  function typeChamp(jeu, champ) {
    var c = colonne(jeu, champ);
    return c ? c.type : 'nombre';
  }

  /* ---------- Filtres ---------- */

  function remplir(select, options, courante) {
    select.innerHTML = '';
    options.forEach(function (o) {
      var opt = document.createElement('option');
      opt.value = o.valeur;
      opt.textContent = o.libelle;
      select.appendChild(opt);
    });
    var existe = options.some(function (o) { return o.valeur === courante; });
    if (existe) { select.value = courante; }
  }

  function jeuxDuTheme(theme) {
    return etat.catalogue.jeux.filter(function (j) { return j.theme === theme; });
  }

  function aIndicateur(jeu, champ) {
    return jeu.indicateurs.some(function (i) { return i.champ === champ; });
  }

  function majFiltres() {
    var jeuxTheme = jeuxDuTheme($('theme').value);

    var territoires = unique(jeuxTheme.map(function (j) { return j.territoire; }));
    remplir($('territoire'), territoires.map(function (t) { return { valeur: t, libelle: t.charAt(0).toUpperCase() + t.slice(1) }; }), $('territoire').value);

    var jeuxTerr = jeuxTheme.filter(function (j) { return j.territoire === $('territoire').value; });
    var indicateurs = [];
    jeuxTerr.forEach(function (j) {
      j.indicateurs.forEach(function (i) {
        if (!indicateurs.some(function (x) { return x.valeur === i.champ; })) {
          indicateurs.push({ valeur: i.champ, libelle: i.libelle });
        }
      });
    });
    remplir($('indicateur'), indicateurs, $('indicateur').value);

    var champ = $('indicateur').value;
    var millesimes = jeuxTerr
      .filter(function (j) { return aIndicateur(j, champ); })
      .map(function (j) { return j.millesime; })
      .sort().reverse();
    remplir($('millesime'), millesimes.map(function (m) { return { valeur: m, libelle: m }; }), $('millesime').value);
  }

  function jeuSelectionne() {
    return etat.catalogue.jeux.filter(function (j) {
      return j.theme === $('theme').value &&
        j.territoire === $('territoire').value &&
        j.millesime === $('millesime').value;
    })[0];
  }

  /* ---------- Données ---------- */

  function chargerGeo(jeu) {
    if (etat.cache[jeu.id]) { return Promise.resolve(etat.cache[jeu.id]); }
    return fetch(jeu.fichiers.geojson)
      .then(function (r) {
        if (!r.ok) { throw new Error('HTTP ' + r.status); }
        return r.json();
      })
      .then(function (geo) { etat.cache[jeu.id] = geo; return geo; });
  }

  function seuils(valeurs, n) {
    var v = valeurs.filter(function (x) { return x !== null; }).sort(function (a, b) { return a - b; });
    var s = [];
    for (var i = 1; i < n; i++) { s.push(v[Math.floor(i * v.length / n)]); }
    return s;
  }

  function classe(v, s) {
    if (v === null) { return -1; }
    var c = 0;
    while (c < s.length && v >= s[c]) { c++; }
    return c;
  }

  /* ---------- Rendu ---------- */

  function dessinerCarte(jeu, geo, champ) {
    if (!etat.carte) {
      etat.carte = L.map('carte', { scrollWheelZoom: false }).setView([48.957, 4.363], 11);
      if (etat.catalogue.site.fond_osm) {
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 18,
          attribution: '© les contributeurs d’OpenStreetMap'
        }).addTo(etat.carte);
      }
    }
    if (etat.couche) { etat.carte.removeLayer(etat.couche); }

    var valeurs = geo.features.map(function (f) { return valeur(f, champ); });
    var s = seuils(valeurs, COULEURS.length);
    var type = typeChamp(jeu, champ);

    etat.couche = L.geoJSON(geo, {
      style: function (f) {
        var c = classe(valeur(f, champ), s);
        var type = f.geometry ? f.geometry.type : '';
        if (/Line/.test(type)) {
          return { color: c < 0 ? '#999999' : LIGNES[c], weight: 3, opacity: 0.9 };
        }
        if (/Point/.test(type)) {
          return { radius: 6, fillColor: c < 0 ? '#cccccc' : COULEURS[c], fillOpacity: 0.9, color: '#1F3A5F', weight: 1 };
        }
        return { fillColor: c < 0 ? '#cccccc' : COULEURS[c], fillOpacity: 0.85, color: '#ffffff', weight: 1.5 };
      },
      pointToLayer: function (f, latlng) {
        return L.circleMarker(latlng, { radius: 6 });
      },
      onEachFeature: function (f, couche) {
        var idf = lire(f, 'id');
        var nom = f.properties.commune || f.properties.code_insee || f.properties.nom || (idf !== undefined ? 'id ' + idf : '');
        couche.bindTooltip('<strong>' + echapper(nom) + '</strong><br>' +
          echapper(libelleIndicateur(jeu, champ)) + ' : ' + echapper(formater(valeur(f, champ), type)));
      }
    }).addTo(etat.carte);

    etat.carte.fitBounds(etat.couche.getBounds(), { padding: [10, 10] });

    var presentes = valeurs.filter(function (v) { return v !== null; });
    if (presentes.length) {
      $('legende-min').textContent = 'Faible (' + formater(Math.min.apply(null, presentes), type) + ')';
      $('legende-max').textContent = 'Élevé (' + formater(Math.max.apply(null, presentes), type) + ')';
    }
  }

  function dessinerTableau(jeu, geo, champ) {
    var thead = $('table-donnees').querySelector('thead');
    var tbody = $('table-donnees').querySelector('tbody');
    thead.innerHTML = '';
    tbody.innerHTML = '';

    var ligne = document.createElement('tr');
    jeu.colonnes.forEach(function (c) {
      var th = document.createElement('th');
      th.scope = 'col';
      th.textContent = c.libelle;
      if (c.type !== 'texte') { th.className = 'num'; }
      ligne.appendChild(th);
    });
    thead.appendChild(ligne);

    var lignes = geo.features.slice().sort(function (a, b) {
      var va = valeur(a, champ), vb = valeur(b, champ);
      if (va === null) { return 1; }
      if (vb === null) { return -1; }
      return vb - va;
    });

    lignes.slice(0, LIGNES_MAX).forEach(function (f) {
      var tr = document.createElement('tr');
      jeu.colonnes.forEach(function (c) {
        var td = document.createElement('td');
        td.textContent = formater(lire(f, c.champ), c.type);
        if (c.type !== 'texte') { td.className = 'num'; }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  function majTelechargements(jeu) {
    $('dl-csv').href = jeu.fichiers.csv;
    $('dl-geojson').href = jeu.fichiers.geojson;
    $('dl-gpkg').href = jeu.fichiers.gpkg;
  }

  function afficher() {
    var jeu = jeuSelectionne();
    var champ = $('indicateur').value;
    if (!jeu) { message('Aucune donnée pour cette combinaison de filtres.'); return; }
    message('');
    chargerGeo(jeu).then(function (geo) {
      $('carte-titre').textContent = libelleIndicateur(jeu, champ) + ', par ' + jeu.territoire + ' (' + jeu.millesime + ')';
      $('carte-source').textContent = 'Source : ' + jeu.source;
      dessinerCarte(jeu, geo, champ);
      dessinerTableau(jeu, geo, champ);
      if (geo.features.length > LIGNES_MAX) {
        message('Tableau limité aux ' + LIGNES_MAX + ' premières lignes sur ' + geo.features.length + ' : le CSV contient tout.');
      }
      majTelechargements(jeu);
    }).catch(function () {
      message('Impossible de charger les données de ce jeu.');
    });
  }

  function remplirDictionnaire() {
    var tbody = $('table-dico').querySelector('tbody');
    tbody.innerHTML = '';
    etat.catalogue.jeux.forEach(function (jeu) {
      jeu.colonnes.forEach(function (c) {
        if (c.champ === 'commune' || c.champ === 'code_insee') { return; }
        var tr = document.createElement('tr');
        [c.libelle, c.definition || '', jeu.theme, jeu.millesime, jeu.territoire, jeu.source].forEach(function (t) {
          var td = document.createElement('td');
          td.textContent = t;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    });
  }

  function remplirPied() {
    var site = etat.catalogue.site;
    $('pied-licence').textContent = site.licence || '';
    $('pied-date').textContent = new Date(etat.catalogue.genere_le).toLocaleDateString('fr-FR');
    var contact = $('pied-contact');
    if (site.contact && site.contact.indexOf('@') > -1 && site.contact.charAt(0) !== '[') {
      var a = document.createElement('a');
      a.href = 'mailto:' + site.contact;
      a.textContent = site.contact;
      contact.appendChild(a);
    } else {
      contact.textContent = site.contact || '';
    }
    $('bandeau-maquette').hidden = !site.maquette;
  }

  /* ---------- Démarrage ---------- */

  function demarrer() {
    fetch('data/catalogue.json', { cache: 'no-cache' })
      .then(function (r) {
        if (!r.ok) { throw new Error('HTTP ' + r.status); }
        return r.json();
      })
      .then(function (catalogue) {
        etat.catalogue = catalogue;
        var themes = unique(catalogue.jeux.map(function (j) { return j.theme; }));
        remplir($('theme'), themes.map(function (t) { return { valeur: t, libelle: t }; }));
        majFiltres();
        remplirDictionnaire();
        remplirPied();

        $('theme').addEventListener('change', function () { majFiltres(); afficher(); });
        $('territoire').addEventListener('change', function () { majFiltres(); afficher(); });
        $('indicateur').addEventListener('change', function () { majFiltres(); afficher(); });
        $('millesime').addEventListener('change', afficher);
        $('btn-afficher').addEventListener('click', afficher);

        afficher();
      })
      .catch(function () {
        message('Impossible de charger le catalogue des données.');
        $('carte-titre').textContent = 'Données indisponibles';
      });
  }

  document.addEventListener('DOMContentLoaded', demarrer);
}());
