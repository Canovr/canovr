# GCloud Build Setup (Base-Image)

## Push-Trigger auf `master` (empfohlen)

Nutze im Cloud-Build-Trigger die Config-Datei `cloudbuild.yaml`.

- Auf jedem Push wird automatisch ein Base-Tag aus `requirements.txt` berechnet.
- Existiert das Base-Image bereits, wird es wiederverwendet.
- Bei geänderten Dependencies wird nur dann ein neues Base-Image gebaut.

## 1) Base-Image selten bauen (nur bei Dependency-Änderungen)

```bash
gcloud builds submit \
  --config cloudbuild.base.yaml \
  --substitutions=_REGION=us-central1,_REPOSITORY=canovr,_BASE_TAG=py310-v1 \
  .
```

## 2) App-Image regelmäßig bauen (schnell, ohne JIT-Neukompilierung)

```bash
gcloud builds submit \
  --config cloudbuild.app.yaml \
  --substitutions=_REGION=us-central1,_REPOSITORY=canovr,_BASE_TAG=py310-v1,_APP_TAG=latest \
  .
```

## 3) Cloud Run deployen

```bash
gcloud run deploy canovr \
  --image us-central1-docker.pkg.dev/$PROJECT_ID/canovr/canovr:latest \
  --region us-central1
```

## Hinweise

- Wenn `requirements.txt` geändert wurde, zuerst Schritt 1 (Base) neu ausführen.
- Wenn nur `app/` geändert wurde, reicht Schritt 2 (App).
- Alternativ komplett automatisch via Push-Trigger mit `cloudbuild.yaml`.
