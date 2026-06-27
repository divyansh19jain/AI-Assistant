# Deployment

Packaging for the AI-Assistant Medicaid form platform. The same `docker-compose.yml`
runs locally on **Docker Desktop** and deploys as a **Coolify** "Docker Compose"
resource on **Proxmox**.

## Architecture

Three containers on one internal network:

| Service    | Image                | Purpose                                  | Public? |
| ---------- | -------------------- | ---------------------------------------- | ------- |
| `db`       | `postgres:15`        | App database (forms, sessions, audit)    | No      |
| `backend`  | built from `backend` | FastAPI API + PDF + workflows            | No      |
| `frontend` | built from `frontend`| Next.js 14 UI (standalone server)        | **Yes** |

**Only the frontend needs a public domain.** The browser calls `/api/*` on the
frontend origin, and the Next server proxies those requests to `backend:8000` over
the internal network (`frontend/next.config.js` rewrites). The backend and database
never have to be exposed to the internet — good for the PHI posture and it means no
backend URL is baked into the client bundle.

> Split-domain alternative: set `NEXT_PUBLIC_API_BASE_URL` to a public backend URL at
> build time and expose the backend with its own domain. Then you must also set
> `CORS_ALLOWED_ORIGINS` to the frontend origin. The same-origin proxy above avoids
> both. Pick one; the default (proxy) is simpler.

The backend self-creates its tables and seeds the bundled form packs on startup
(`app/main.py` lifespan), so no separate migration step is required to boot.

---

## 1. Local Docker Desktop

Prerequisites: Docker Desktop running.

```bash
cp .env.example .env          # edit secrets if you like; defaults are mock-safe
docker compose up --build -d
```

Open:

- App:     http://localhost:3000
- API docs: http://localhost:8000/docs   (bound to localhost only)

The UI shows the yellow **MOCK-mode** banner because `USE_MOCK_EMR=true`. Stop with
`docker compose down` (add `-v` to also drop the database + generated-PDF volumes).

### Hot-reload dev variant

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

This bind-mounts the source and runs `uvicorn --reload` + `next dev`. (The native
workflow in `AGENTS.md` — venv + `npm run dev`, using only `docker compose up db -d`
— still works too.)

---

## 2. Coolify on Proxmox

Coolify deploys this repo as a **Docker Compose** application. High level: point
Coolify at the repo, set the env vars, give the `frontend` service a domain, deploy.

### Steps

1. **Create the resource**
   - Coolify -> your Project -> **+ New** -> **Application** -> **Docker Compose**
     (or **Public/Private Git Repository**, then choose the "Docker Compose" build pack).
   - Connect this repository and branch (`main`).
   - Coolify auto-detects `docker-compose.yml` at the repo root.

2. **Set environment variables** (Coolify -> resource -> **Environment Variables**).
   These map to the `${...}` placeholders in the compose file. At minimum, change the
   secrets:

   ```env
   APP_ENV=production
   POSTGRES_PASSWORD=<a-strong-password>
   ADMIN_USERNAME=<your-admin>
   ADMIN_PASSWORD=<a-strong-password>
   ADMIN_JWT_SECRET=<a-long-random-string>
   USE_MOCK_EMR=true
   WEB_SUBMIT_DRIVER=mock
   # Leave empty -> same-origin /api proxy (recommended):
   NEXT_PUBLIC_API_BASE_URL=
   BACKEND_INTERNAL_URL=http://backend:8000
   ```

   Add `OPENAI_API_KEY` / EMR / voice keys only when you intend to enable them.

3. **Assign a domain to `frontend`**
   - In the resource's service/domain settings, set the domain (e.g.
     `https://forms.example.com`) on the **frontend** service, port **3000**.
   - Coolify's Traefik proxy + Let's Encrypt handle TLS. Do **not** add a domain to
     `backend` or `db` — they stay internal.
   - Tip: you can drop the host `ports:` publishing for `backend`/`db` on the server
     since Coolify routes by domain over the internal network; it is bound to
     `127.0.0.1` already, so leaving it is harmless.

4. **Persistent storage** — these named volumes already persist across redeploys:
   - `pgdata` — the Postgres database (back this up).
   - `pdf_data` — generated PDFs.

5. **Deploy.** Coolify builds the images (the frontend build arg
   `NEXT_PUBLIC_API_BASE_URL` defaults to empty -> proxy mode) and starts the stack.
   Watch the deploy logs until `backend` passes its `/health` check.

### Notes for Coolify

- **Rebuild on backend URL change?** No — with the proxy the backend URL is never
  baked into the client. Only a split-domain setup requires rebuilding when the
  backend domain changes.
- **Multiple apps on one host:** the `frontend` host port publish (`3000:3000`) can
  collide if you run several stacks. Coolify routes by domain regardless; if you hit a
  conflict, set `FRONTEND_PORT` to a free port or remove the publish and rely on the
  domain.
- **Database backups:** use Coolify's scheduled backups against the `db` service /
  `pgdata` volume.

---

## Environment variables

| Variable                  | Default                   | Notes                                              |
| ------------------------- | ------------------------- | -------------------------------------------------- |
| `APP_ENV`                 | `production`              | `production` locks CORS; `development` is permissive |
| `POSTGRES_USER/PASSWORD/DB` | `ai_assistant`          | **Change the password** off localhost              |
| `USE_MOCK_EMR`            | `true`                    | `false` requires `EMR_DATABASE_URL` (read-only)    |
| `EMR_DATABASE_URL`        | empty                     | Real EMR DSN; only when `USE_MOCK_EMR=false`       |
| `OPENAI_API_KEY`          | empty                     | Empty -> rule-based fallback                        |
| `OPENAI_MODEL`            | `gpt-5.4-mini`            | Configurable model id                              |
| `WEB_SUBMIT_DRIVER`       | `mock`                    | `mock` = safe dry-run; real drivers are PHI egress |
| `ADMIN_USERNAME/PASSWORD` | `admin` / `admin1234`     | **Change before any non-local deploy**             |
| `ADMIN_JWT_SECRET`        | `change-me-in-production` | **Change** — long random string                    |
| `CORS_ALLOWED_ORIGINS`    | empty                     | Only for split-domain; unused with the proxy       |
| `NEXT_PUBLIC_API_BASE_URL`| empty                     | Empty = same-origin proxy; absolute = split-domain |
| `BACKEND_INTERNAL_URL`    | `http://backend:8000`     | Internal target for the Next `/api` proxy          |
| `FRONTEND/BACKEND/DB_PORT`| `3000` / `8000` / `5499`  | Host port publishing                               |

## Security checklist before going live

- [ ] Changed `POSTGRES_PASSWORD`, `ADMIN_PASSWORD`, and `ADMIN_JWT_SECRET`.
- [ ] `APP_ENV=production` (and `CORS_ALLOWED_ORIGINS` set if using split-domain).
- [ ] `.env` is **not** committed (it is gitignored) — secrets live in Coolify's env UI.
- [ ] `USE_MOCK_EMR=false` only with a genuine **read-only** EMR DSN.
- [ ] `WEB_SUBMIT_DRIVER` left as `mock` unless a real portal driver is intended.
- [ ] HTTPS enforced on the frontend domain (Coolify default).
- [ ] `pgdata` backups scheduled.

## Troubleshooting

- **Frontend loads but API calls 404/blocked:** confirm `BACKEND_INTERNAL_URL` resolves
  (service name `backend` on the shared network) and `NEXT_PUBLIC_API_BASE_URL` is
  empty. Check `docker compose logs frontend backend`.
- **Backend unhealthy:** `docker compose logs backend`; verify `db` is healthy and
  `APP_DATABASE_URL` points at the `db` service.
- **CORS errors in a split-domain setup:** set `CORS_ALLOWED_ORIGINS` to the exact
  frontend origin and keep `APP_ENV=production`.
- **Port already in use (local):** change `FRONTEND_PORT` / `BACKEND_PORT` / `DB_PORT`
  in `.env`.
