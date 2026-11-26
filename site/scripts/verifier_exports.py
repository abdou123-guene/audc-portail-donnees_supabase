#!/usr/bin/env python3
"""Contrôle les fichiers de docs/data avant publication."""
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOCS = RACINE / "docs"
TAILLE_MAX_MO = 50
INTERDITS = {"proprietaire", "propriétaire", "nom_proprietaire", "ddenom",
             "date_naissance", "telephone", "email", "mot_de_passe"}


def main():
    erreurs = []
    chemin = DOCS / "data" / "catalogue.json"
    if not chemin.exists():
        sys.exit("docs/data/catalogue.json introuvable")
    catalogue = json.loads(chemin.read_text(encoding="utf-8"))
    if not catalogue.get("jeux"):
        erreurs.append("le catalogue ne contient aucun jeu")
    for jeu in catalogue.get("jeux", []):
        for nom in ("geojson", "csv", "gpkg"):
            fichier = DOCS / jeu["fichiers"][nom]
            if not fichier.exists():
                erreurs.append(f"{jeu['id']} : fichier manquant {fichier.name}")
            elif fichier.stat().st_size > TAILLE_MAX_MO * 1024 * 1024:
                erreurs.append(f"{jeu['id']} : {fichier.name} dépasse {TAILLE_MAX_MO} Mo")
        for colonne in jeu["colonnes"]:
            if colonne["champ"].lower() in INTERDITS:
                erreurs.append(f"{jeu['id']} : colonne interdite {colonne['champ']}")
    if erreurs:
        print("ERREURS :")
        for e in erreurs:
            print(" -", e)
        sys.exit(1)
    print(f"OK : {len(catalogue['jeux'])} jeu(x) vérifié(s)")


if __name__ == "__main__":
    main()
