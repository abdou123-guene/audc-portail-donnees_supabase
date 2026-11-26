#!/usr/bin/env python3
"""Exporte toutes les vues d'un schéma PostGIS vers docs/data/ (mode automatique).

Pour chaque vue (ou vue matérialisée) du schéma indiqué dans config/indicateurs.yml :
un GeoJSON (carte web), un CSV (tableur) et un GeoPackage (SIG), puis met à jour
docs/data/catalogue.json.

Usage :
    python scripts/export_donnees.py                    # toutes les vues
    python scripts/export_donnees.py --vue vue_obstacle # une seule vue
    python scripts/export_donnees.py --lister           # liste les vues, sans exporter
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

RACINE = Path(__file__).resolve().parent.parent
CONFIG = RACINE / "config" / "indicateurs.yml"
SORTIE = RACINE / "docs" / "data"
MOTIF_SCHEMA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENTIERS = {"smallint", "integer", "bigint"}
NOMBRES = ("numeric", "double precision", "real")


def creer_connexion():
    """Crée la connexion à partir des variables du fichier .env."""
    load_dotenv(RACINE / ".env")
    requis = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]
    manquants = [v for v in requis if not os.getenv(v)]
    if manquants:
        sys.exit("Variables manquantes dans .env : " + ", ".join(manquants))
    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        database=os.environ["PGDATABASE"],
        query={"sslmode": os.getenv("PGSSLMODE", "require")},
    )
    return create_engine(url, connect_args={"connect_timeout": 15})


def identifiant(nom):
    """Nom de fichier sûr : minuscules, chiffres et underscores."""
    return re.sub(r"[^a-z0-9_]+", "_", nom.lower()).strip("_")


def type_champ(pg):
    """Type PostgreSQL -> type du portail (texte, entier, nombre)."""
    t = pg.lower()
    if t in ENTIERS:
        return "entier"
    if t.startswith(NOMBRES):
        return "nombre"
    return "texte"


def lister_vues(moteur, schema, avec_matviews):
    genres = "('v','m')" if avec_matviews else "('v')"
    sql = text(
        "SELECT c.relname AS nom, obj_description(c.oid, 'pg_class') AS commentaire "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE n.nspname = :schema AND c.relkind IN {genres} ORDER BY c.relname"
    )
    with moteur.connect() as cx:
        return [(r.nom, r.commentaire) for r in cx.execute(sql, {"schema": schema})]


def lire_colonnes(moteur, schema, nom):
    sql = text(
        "SELECT a.attname AS nom, format_type(a.atttypid, a.atttypmod) AS type "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = :nom AND a.attnum > 0 "
        "AND NOT a.attisdropped ORDER BY a.attnum"
    )
    with moteur.connect() as cx:
        return [(r.nom, r.type) for r in cx.execute(sql, {"schema": schema, "nom": nom})]


def est_geo(pg):
    return "geometry" in pg.lower() or "geography" in pg.lower()


def decrire(schema, nom, commentaire, colonnes_pg, src, reglage):
    """Construit la description d'un jeu (entrée de catalogue sans les fichiers)."""
    geom = src["colonne_geometrie"]
    if not any(c == geom and est_geo(t) for c, t in colonnes_pg):
        raise ValueError(f"pas de colonne de géométrie « {geom} »")
    cle = src["colonne_id"]
    exclues = {c.lower() for c in src.get("colonnes_exclues", [])}
    exclues |= {c.lower() for c in reglage.get("colonnes_exclues", [])}
    definitions = reglage.get("definitions", {})

    colonnes = []
    for champ, pg in colonnes_pg:
        if est_geo(pg) or champ.lower() in exclues:
            continue
        # l'identifiant est traité comme du texte : pas de séparateur de milliers
        type_ = "texte" if champ == cle else type_champ(pg)
        colonnes.append({"champ": champ, "libelle": champ, "type": type_,
                         "definition": definitions.get(champ, ""), "pg": pg})
    colonnes.sort(key=lambda c: c["champ"] != cle)  # l'identifiant en premier

    presents = [c["champ"] for c in colonnes]
    if "indicateurs" in reglage:
        champs_ind = [c for c in reglage["indicateurs"] if c in presents]
    else:
        champs_ind = [c["champ"] for c in colonnes
                      if c["type"] in ("entier", "nombre") and c["champ"] != cle]
    if not champs_ind and cle in presents:
        champs_ind = [cle]          # repli : colorer selon l'identifiant
    if not champs_ind:
        raise ValueError("aucune colonne utilisable comme indicateur")

    return {
        "id": identifiant(nom),
        "vue": nom,
        "theme": reglage.get("libelle") or commentaire or nom,
        "territoire": schema,
        "millesime": str(datetime.now().year),
        "source": reglage.get("source") or src["source_defaut"],
        "simplification_m": float(reglage.get("simplification_m", src["simplification_m"])),
        "geom": geom,
        "cle": cle,
        "colonnes": [{k: v for k, v in c.items() if k != "pg"} for c in colonnes],
        "types_pg": {c["champ"]: c["pg"] for c in colonnes},
        "indicateurs": [{"champ": c, "libelle": c} for c in champs_ind],
        "avertissements": [] if cle in presents else [f"colonne « {cle} » absente"],
    }


def lire_vue(moteur, schema, jeu, srid_defaut):
    """Lit une vue avec uniquement les colonnes retenues (+ géométrie)."""
    if not MOTIF_SCHEMA.match(schema):
        sys.exit(f"Nom de schéma invalide : {schema}")
    guillemets = lambda s: '"' + s.replace('"', '""') + '"'
    champs = [c["champ"] for c in jeu["colonnes"]]
    colonnes_sql = ", ".join(guillemets(c) for c in champs + [jeu["geom"]])
    sql = f'SELECT {colonnes_sql} FROM {guillemets(schema)}.{guillemets(jeu["vue"])}'
    gdf = gpd.read_postgis(sql, moteur, geom_col=jeu["geom"])
    if gdf.crs is None:
        gdf = gdf.set_crs(srid_defaut)
    if jeu["geom"] != "geom":
        gdf = gdf.rename_geometry("geom")
    # colonnes json / tableaux / hstore : converties en texte
    for champ, pg in jeu["types_pg"].items():
        if pg.lower() in ("json", "jsonb", "hstore") or pg.endswith("[]"):
            gdf[champ] = gdf[champ].map(lambda v: None if v is None else str(v))
    return gdf


def exporter_jeu(jeu, gdf):
    """Écrit les trois fichiers d'un jeu et renvoie son entrée de catalogue."""
    identifiant_jeu = jeu["id"]
    if len(gdf) == 0:
        raise ValueError("la vue ne contient aucune ligne")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if len(gdf) == 0:
        raise ValueError("aucune géométrie exploitable")
    gdf["geom"] = gdf.geometry.make_valid()

    avertissements = list(jeu["avertissements"])
    cle = jeu["cle"]
    if cle in gdf.columns and gdf[cle].duplicated().any():
        avertissements.append(f"valeurs en double dans « {cle} »")

    SORTIE.mkdir(parents=True, exist_ok=True)
    chemin_geojson = SORTIE / f"{identifiant_jeu}.geojson"
    chemin_csv = SORTIE / f"{identifiant_jeu}.csv"
    chemin_gpkg = SORTIE / f"{identifiant_jeu}.gpkg"

    # 1) GeoPackage : géométries et projection d'origine (SIG)
    if chemin_gpkg.exists():
        chemin_gpkg.unlink()
    gdf.to_file(chemin_gpkg, layer=identifiant_jeu, driver="GPKG")

    # 2) GeoJSON : simplifié et reprojeté en WGS84 (carte web)
    web = gdf.copy()
    if jeu["simplification_m"] > 0:
        web["geom"] = web.geometry.simplify(jeu["simplification_m"], preserve_topology=True)
    web = web.to_crs(4326)
    if chemin_geojson.exists():
        chemin_geojson.unlink()
    web.to_file(chemin_geojson, driver="GeoJSON", COORDINATE_PRECISION=5)

    # 3) CSV : sans géométrie, séparateur ; et virgule décimale (Excel français)
    tableau = pd.DataFrame(gdf.drop(columns="geom"))
    tableau.to_csv(chemin_csv, sep=";", decimal=",", index=False, encoding="utf-8-sig")

    geometrie = gdf.geom_type.str.replace("Multi", "", regex=False).mode().iat[0]
    return {
        "id": identifiant_jeu,
        "vue": jeu["vue"],
        "theme": jeu["theme"],
        "territoire": jeu["territoire"],
        "millesime": jeu["millesime"],
        "source": jeu["source"],
        "geometrie": geometrie,
        "srid_origine": int(gdf.crs.to_epsg() or 0),
        "colonnes": jeu["colonnes"],
        "indicateurs": jeu["indicateurs"],
        "nb_objets": int(len(gdf)),
        "avertissements": avertissements,
        "fichiers": {
            "geojson": f"data/{identifiant_jeu}.geojson",
            "csv": f"data/{identifiant_jeu}.csv",
            "gpkg": f"data/{identifiant_jeu}.gpkg",
        },
    }


def main():
    parseur = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parseur.add_argument("--vue", help="nom d'une seule vue à exporter")
    parseur.add_argument("--lister", action="store_true", help="liste les vues sans exporter")
    args = parseur.parse_args()

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    src = config["source"]
    schema = src["schema"]
    reglages = config.get("vues") or {}
    if not MOTIF_SCHEMA.match(schema):
        sys.exit(f"Nom de schéma invalide : {schema}")

    moteur = creer_connexion()
    vues = [(n, c) for n, c in lister_vues(moteur, schema, src["inclure_vues_materialisees"])
            if n not in src.get("exclure_vues", [])]
    if not vues:
        sys.exit(f"Aucune vue trouvée dans le schéma « {schema} » (nom ? droits ?)")
    if args.lister:
        for nom, _ in vues:
            print(nom)
        return
    selection = [v for v in vues if v[0] == args.vue] if args.vue else vues
    if not selection:
        sys.exit(f"Vue inconnue : {args.vue}")

    entrees, echecs = {}, []
    for nom, commentaire in selection:
        print(f"Export de {schema}.{nom} ...")
        try:
            jeu = decrire(schema, nom, commentaire, lire_colonnes(moteur, schema, nom),
                          src, reglages.get(nom, {}))
            gdf = lire_vue(moteur, schema, jeu, src["srid_defaut"])
            entree = exporter_jeu(jeu, gdf)
            entrees[entree["id"]] = entree
            for a in entree["avertissements"]:
                print(f"   attention : {a}")
        except Exception as erreur:  # une vue en échec ne bloque pas les autres
            echecs.append((nom, str(erreur)))
            print(f"   ÉCHEC : {erreur}")

    # Catalogue : on garde les entrées existantes des vues non réexportées.
    chemin_catalogue = SORTIE / "catalogue.json"
    anciens = {}
    if chemin_catalogue.exists():
        ancien = json.loads(chemin_catalogue.read_text(encoding="utf-8"))
        anciens = {j["id"]: j for j in ancien.get("jeux", [])}
    anciens.update(entrees)
    ordre = [identifiant(n) for n, _ in vues if identifiant(n) in anciens]
    catalogue = {
        "genere_le": datetime.now().isoformat(timespec="seconds"),
        "site": config["site"],
        "jeux": [anciens[i] for i in ordre],
    }
    SORTIE.mkdir(parents=True, exist_ok=True)
    chemin_catalogue.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    print(f"Terminé : {len(entrees)} vue(s) exportée(s), {len(echecs)} échec(s).")
    if echecs:
        for nom, e in echecs:
            print(f" - {nom} : {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
