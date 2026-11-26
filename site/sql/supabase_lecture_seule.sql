-- À exécuter dans Supabase > SQL Editor (facultatif en test, recommandé ensuite).
-- Crée un compte limité à la lecture du schéma publié.
CREATE ROLE partage_ro LOGIN PASSWORD 'CHANGER_CE_MOT_DE_PASSE';

GRANT USAGE ON SCHEMA geo_standards TO partage_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA geo_standards TO partage_ro;  -- couvre vues et vues matérialisées
ALTER DEFAULT PRIVILEGES IN SCHEMA geo_standards GRANT SELECT ON TABLES TO partage_ro;

-- PostGIS est souvent installé dans le schéma « extensions » sur Supabase.
GRANT USAGE ON SCHEMA extensions TO partage_ro;

-- Vérification
SELECT table_name FROM information_schema.role_table_grants
WHERE grantee = 'partage_ro' AND table_schema = 'geo_standards' ORDER BY 1;
