# Portail de données partagées – AUDC (version test Supabase)

Site statique qui présente toutes les vues du schéma `geo_standards` d'une base Supabase (carte, tableau, téléchargements).

## Principe

1. `scripts/export_donnees.py` découvre les vues (et vues matérialisées) du schéma indiqué dans `config/indicateurs.yml`.
2. Pour chacune, il écrit GeoJSON, CSV et GeoPackage dans `docs/data/`, plus un `catalogue.json`.
3. GitHub Pages publie le dossier `docs/`.

Chaque vue doit avoir une colonne de géométrie `geom` et une colonne `id`. Les colonnes numériques deviennent des indicateurs pour colorer la carte (repli : `id`).

## Connexion à Supabase

1. Dans Supabase, cliquer sur **Connect** et copier les paramètres du **Session pooler**.
2. Copier `.env.example` en `.env` et remplir les valeurs. Utilisateur : `postgres.<ref>`.
3. Facultatif : exécuter `sql/supabase_lecture_seule.sql` pour créer un compte `partage_ro` limité à la lecture.

## Mise à jour des données

```
.venv\Scripts\Activate.ps1          # Windows (macOS/Linux : source .venv/bin/activate)
python scripts/export_donnees.py --lister   # contrôle de la connexion
python scripts/export_donnees.py
python scripts/verifier_exports.py
git add docs/data
git commit -m "Mise à jour des données"
git push
```

## Configuration

- `config/indicateurs.yml` : schéma, options, réglages facultatifs par vue.
- `.env` (non versionné) : paramètres de connexion. Modèle : `.env.example`.

## Sécurité

Ne jamais ajouter `.env` ni un mot de passe au dépôt. Tout ce qui est dans `docs/data` est public, historique Git compris : ne publier que des vues sans donnée personnelle. Le contrôle `verifier_exports.py` refuse certains noms de colonnes (propriétaire, email, etc.) ; `colonnes_exclues` dans la config permet d'en retirer d'autres.
