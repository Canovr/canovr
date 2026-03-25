# CanovR Backend Release Checklist

## Security Gate
- [ ] `CANOVR_DEBUG=false` in Production gesetzt
- [ ] `CANOVR_JWT_SECRET` gesetzt (und sicher verwaltet)
- [ ] Optional: `CANOVR_OAUTH_STATE_SECRET` gesetzt
- [ ] Keine sensitiven Daten in Logs (Token/Passwort/PII)
- [ ] Strava-Tokens werden nicht persistent gespeichert

## Quality Gate
- [ ] `./scripts/release_gate.sh` erfolgreich
- [ ] Auth-Flow grün: Register, Login, Refresh, Logout, `/api/auth/me`, Delete
- [ ] `/api/auth/me` liefert `athlete_id` korrekt
- [ ] Validierungsfehler liefern 4xx (keine 500 bei erwartbaren Eingaben)

## Deploy Gate
- [ ] Cloud Build mit Test-Stufe erfolgreich (`cloudbuild.yaml` / `cloudbuild.app.yaml`)
- [ ] Migration-Job (`alembic upgrade head`) vor Deploy ausgeführt
- [ ] Smoke-Test nach Deploy erfolgreich (`/`, `/api/auth/me` mit gültigem Token)

## Compliance Gate
- [ ] Privacy- und Impressum-Seiten erreichbar
- [ ] Datenschutzerklärung spiegelt reale Betriebsumgebung wider
