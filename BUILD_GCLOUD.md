# GCloud Build + Turso Deployment

## Zielsetup

- `prod`: Turso/libSQL (`TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN`)
- `lokal`: SQLite (`CANOVR_DB_PATH`, default `canovr.db`)
- Schema-Änderungen in allen Umgebungen über Alembic (`alembic upgrade head`)

## Env-Contract

- Production (verbindlich):
- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- `CANOVR_JWT_SECRET`
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- Lokal (optional):
- `CANOVR_DB_PATH`
- `CANOVR_AUTO_CREATE_SCHEMA` (`true|false`, default `true`)
- `CANOVR_DEBUG` (`true|false`, default `false`)
- `CANOVR_OAUTH_STATE_SECRET` (optional, fallback auf `CANOVR_JWT_SECRET`)
- `CANOVR_APPLE_TEAM_ID` (default `M944LR67TZ`)
- `CANOVR_IOS_BUNDLE_ID` (default `com.canovr.app`)

## 1) Base-Image (bei Dependency-Änderungen)

```bash
gcloud builds submit \
  --config cloudbuild.base.yaml \
  --substitutions=_REGION=us-central1,_REPOSITORY=canovr,_BASE_TAG=py310-v1 \
  .
```

## 2) App-Image (regelmäßig)

```bash
gcloud builds submit \
  --config cloudbuild.app.yaml \
  --substitutions=_REGION=us-central1,_REPOSITORY=canovr,_BASE_TAG=py310-v1,_APP_TAG=latest \
  .
```

## 3) Migration-Job einmalig bereitstellen (oder aktualisieren)

Der Job nutzt dasselbe App-Image und führt nur Migrationen aus.

```bash
gcloud run jobs deploy canovr-migrate \
  --image us-central1-docker.pkg.dev/$PROJECT_ID/canovr/canovr:latest \
  --region us-central1 \
  --command alembic \
  --args upgrade,head
```

Hinweis: Stelle sicher, dass der Job dieselben `TURSO_*` Variablen wie der Service bekommt.

## 4) Migrationen ausführen (vor jedem Deploy)

Direkt:

```bash
gcloud run jobs execute canovr-migrate --region us-central1 --wait
```

Oder über Cloud Build:

```bash
gcloud builds submit \
  --config cloudbuild.migrate.yaml \
  --substitutions=_REGION=us-central1,_MIGRATION_JOB=canovr-migrate \
  .
```

## 5) Service deployen

```bash
gcloud run deploy canovr \
  --image us-central1-docker.pkg.dev/$PROJECT_ID/canovr/canovr:latest \
  --region us-central1
```

## Standard-Reihenfolge

1. Tests (werden in Cloud Build automatisch vor dem Build ausgefuehrt)
2. Build Image
3. Migration Job ausführen
4. Service deployen

## Post-Deploy Check (30-60 Minuten)

Nach dem Deploy die folgenden Signale prüfen:

- `429` Antworten
- `504` Antworten
- Cloud-Run Warnung `no available instance`
- p95/p99 Latenz für `/api/athletes/` und `/api/athletes/{id}/week`

Wenn weiter auffällig:

```bash
gcloud run services update canovr \
  --project "$PROJECT_ID" \
  --region europe-west3 \
  --concurrency 8 \
  --max-instances 10 \
  --min-instances 1
```

Ziel: weniger Queueing und weniger Request-Abbrüche unter Last.

## Lokaler Workflow

```bash
# Ohne TURSO_* -> lokale SQLite
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

## Rollback-Hinweise

- App-Rollback: vorheriges Image auf Cloud Run deployen.
- Schema-Rollback: gezielt über Alembic, z.B. `alembic downgrade -1` (als Job-Command).
