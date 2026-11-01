# Deploying to the cloud (Render + Supabase + Upstash + GCP)

A free-tier stack: Render runs the API (which also serves the
dashboard at `/ui`) from this repo's own `Dockerfile`; Supabase
provides PostgreSQL; Upstash provides Redis; the worker runs on a free
Google Cloud "Always Free" VM. Four providers, not one, because no
single free tier covers everything this project needs - specifically,
Render's free tier doesn't include a Background Worker service, only
Web Services, so the worker (a process that must run forever, not
something a serverless/request-triggered platform can host) needs
somewhere else to live.

Nothing here has been deployed and verified end-to-end from this
development machine (no Docker, and no access to create third-party
cloud accounts) - this is a reviewed, best-effort guide, not a
"confirmed working" claim. If a step doesn't match what you see in
these dashboards, their UIs change; the connection-string shapes, env
var names, and the systemd service file are the part that actually
matters and is stable.

## 1. PostgreSQL on Supabase

1. Create a project at [supabase.com](https://supabase.com) (free tier).
2. Project Settings → Database → Connection string. Use the **direct
   connection** (port `5432`), not the "Transaction pooler" (port
   `6543`/PgBouncer). This project's `asyncpg` driver uses server-side
   prepared statements by default, which PgBouncer's transaction-pooling
   mode doesn't support correctly - connecting through the pooler can
   cause intermittent "prepared statement already exists" errors under
   concurrent load. Direct connection has no such issue and this
   project's connection counts (one API instance, one worker) are well
   within what a free-tier direct connection limit allows.
3. Supabase gives you `postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres`.
   Change the scheme to `postgresql+asyncpg://` (this project's
   `DATABASE_URL` always needs that driver prefix - see
   `src/pulsequeue/core/config.py`):

   ```
   postgresql+asyncpg://postgres:[password]@db.[ref].supabase.co:5432/postgres
   ```

   That's the value for `DATABASE_URL` everywhere below. Migrations run
   automatically on every Render deploy (see `render.yaml`'s
   `dockerCommand`) - you don't need to run `alembic upgrade head`
   against Supabase yourself.

## 2. Redis on Upstash

1. Create a database at [upstash.com](https://upstash.com) (free tier).
2. Copy the `rediss://` connection string (TLS; Upstash doesn't expose
   a plain `redis://` endpoint) from the database's dashboard - it
   looks like `rediss://default:[password]@[endpoint].upstash.io:6379`.
3. That's the value for `REDIS_URL`. Redis is optional in this
   project's design (ADR 0002) - if you'd rather not sign up for a
   fourth service, leave `REDIS_URL` unset everywhere below; the app
   falls back to a default that will simply be unreachable in this
   deployment, and everything still works, just with the worker polling
   on its own schedule instead of an instant wake-up (logged as
   warnings, not errors).

## 3. API + dashboard on Render

1. Push this repo to GitHub (already done if you're reading this from
   the repo itself).
2. Render dashboard → New → **Blueprint** → connect the repo. Render
   reads [`render.yaml`](../render.yaml) and proposes one service,
   `pulsequeue-api` (a free Web Service).
3. Fill in:
   - `DATABASE_URL` - the Supabase connection string from step 1.
   - `REDIS_URL` - the Upstash connection string from step 2 (or leave
     unset per the note above).
   - `PULSEQUEUE_ADMIN_TOKEN` - a real random value, not the repo's
     `change-me-locally` default. This gates the dead-letter
     listing/requeue endpoints and the dashboard's dead-letter panel.
     (`python -c "import secrets; print(secrets.token_urlsafe(32))"`
     generates one.)
4. Deploy. The service applies migrations on boot, then starts.
5. Visit `https://<your-service>.onrender.com/ui/` for the dashboard,
   or `https://<your-service>.onrender.com/docs` for the interactive
   API docs. Tasks will sit `queued` until the worker (step 4 below) is
   also running.

**Free-tier cold starts**: Render's free web services sleep after ~15
minutes idle; the next request wakes it (expect a 30-60s delay on that
first request). Fine for a portfolio demo, not for anything
latency-sensitive. `PULSEQUEUE_ALLOWED_ORIGINS` doesn't need to be set
for this deployment - the dashboard is served by the same API process
at the same origin, so no CORS configuration is needed between them.

## 4. Worker on a free Google Cloud VM

Google Cloud's "Always Free" tier includes one `e2-micro` instance
(perpetually free, not a time-boxed trial) in `us-west1`, `us-central1`,
or `us-east1`. The worker makes only outbound connections (to Supabase
and Upstash) - no inbound firewall rules are needed.

1. In the GCP Console: Compute Engine → VM Instances → Create Instance.
   - Region: one of the three above (required for the free tier).
   - Machine type: `e2-micro`.
   - Boot disk: Ubuntu 24.04 LTS (ships Python 3.12, which this
     project's `requires-python = ">=3.11,<3.13"` accepts - no need to
     install a separate Python version).
   - Leave firewall options unchecked (no HTTP/HTTPS traffic needed -
     the worker doesn't listen on any port).
2. SSH in (the Console's browser-based SSH button works, no local
   setup needed).
3. Copy [`deploy/gcp/setup.sh`](../deploy/gcp/setup.sh) onto the VM
   and run it - or just run this, which does the same thing:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/ayrus15/PulseQueue/main/deploy/gcp/setup.sh -o setup.sh
   bash setup.sh
   ```

4. The first run creates `/opt/pulsequeue/.env` with placeholder
   values and stops, telling you to edit it:

   ```bash
   nano /opt/pulsequeue/.env
   ```

   Replace the placeholders with your real `DATABASE_URL` (Supabase,
   step 1) and `REDIS_URL` (Upstash, step 2 - or delete that line
   entirely if you're skipping Redis).
5. Run `bash setup.sh` again. This time it installs
   [`deploy/gcp/pulsequeue-worker.service`](../deploy/gcp/pulsequeue-worker.service)
   as a systemd service, running as a dedicated unprivileged
   `pulsequeue` system user, and starts it.
6. Check it's actually running:

   ```bash
   sudo systemctl status pulsequeue-worker
   sudo journalctl -u pulsequeue-worker -f   # live logs
   ```

   You should see `"Worker starting"` and, once you submit a task from
   the dashboard, `"Processing task"` / `"Task succeeded"` lines.

**Updating later**: `cd /opt/pulsequeue && git pull && .venv/bin/pip
install -e . && sudo systemctl restart pulsequeue-worker`.

## Architecture this produces

```
Browser --HTTPS--> Render (API + /ui dashboard)
                        |
                        +--queries/writes--> Supabase (PostgreSQL)
                        |
                        +--best-effort notify--> Upstash (Redis)
                                                      |
GCP VM (worker, systemd) --polls-------------> Supabase (PostgreSQL)
                          <--best-effort wake--- Upstash (Redis)
```

The API and worker never talk to each other directly - exactly the
same "coordinate only through PostgreSQL, Redis is optional" design as
a local run (see [`docs/architecture.md`](architecture.md)), just with
each piece on a different free-tier host instead of the same machine.

## Things to verify yourself, not asserted here

- Google Cloud's free-tier terms, region availability, and whether
  your account still has Always Free eligibility (some promotional
  credits and the Always Free tier are different things) - check the
  GCP Console's billing page.
- Whether a `t2d`/`e2` family or region substitution is still called
  "Always Free" by the time you read this - cloud free tiers change
  faster than this doc will be kept in sync with them.
