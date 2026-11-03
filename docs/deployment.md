# Deploying to the cloud (Render + Supabase + Upstash)

A free-tier stack, no credit card required anywhere: Render runs the
API, the dashboard (`/ui`), and - by default - the worker too, all in
one free Web Service, from this repo's own `Dockerfile`; Supabase
provides PostgreSQL; Upstash provides Redis.

Not deployed from this development machine itself (no Docker, and no
access to create third-party cloud accounts here) - but this exact
guide is what the repository owner followed for a real Render
deployment, which is now **live**:
[pulsequeue-api-ueyd.onrender.com/ui/](https://pulsequeue-api-ueyd.onrender.com/ui/).
Every gotcha documented below (Render not interpreting shell syntax in
`dockerCommand`, Supabase's direct connection being IPv6-only, a
password needing percent-encoding, and that in turn breaking Alembic's
`ConfigParser`-based config) is something that actually happened and
was actually fixed during that deployment, not guessed in advance. If
a step doesn't match what you see in these dashboards, their UIs
change; the connection-string shapes and env var names are the part
that actually matters and is stable.

## Why the worker runs in the API process here

This project's real, tested, documented architecture is two
independent processes - the API and the worker never share process
state (see [`docs/architecture.md`](architecture.md)). That's still
how you should run it anywhere you can.

For *this specific* free deployment, though: Render's free tier only
offers Web Services, not a Background Worker, and the obvious
alternative - a free cloud VM (Google Cloud or Oracle Cloud's "Always
Free" tiers) - still requires putting a credit card on file, which
this guide avoids entirely. So `render.yaml` sets
`PULSEQUEUE_RUN_WORKER_IN_PROCESS=true`, which runs the worker as a
background task inside the same API process
(`src/pulsequeue/main.py`'s `lifespan`) instead of as its own process.
It's an explicit, logged, documented concession for this one
constraint - not a claim that this is the right way to run it in
general. If you'd rather keep the two processes genuinely separate and
don't mind a card on file, see "Alternative: a separate worker on a
free GCP VM" at the bottom.

## 1. PostgreSQL on Supabase

1. Create a project at [supabase.com](https://supabase.com) (free tier).
2. Project Settings → Database → Connection string. Use the **Session
   pooler** connection string - not "Direct connection" and not
   "Transaction pooler". Confirmed live, on an actual Render deploy:
   - **Direct connection** (`db.[ref].supabase.co:5432`) is IPv6-only
     for most new Supabase projects, and Render's network doesn't
     support outbound IPv6 - migrations failed outright with
     `socket.gaierror: Name or service not known` (the hostname
     couldn't even resolve).
   - **Transaction pooler** (port `6543`) is IPv4-reachable, but this
     project's `asyncpg` driver uses server-side prepared statements by
     default, which PgBouncer's transaction-pooling mode doesn't
     support correctly - this can cause intermittent "prepared
     statement already exists" errors under concurrent load.
   - **Session pooler** (port `5432`, on the pooler host) is
     IPv4-reachable *and* keeps one dedicated backend connection per
     client session (not swapped per-transaction like the transaction
     pooler), so prepared statements work correctly too. This is the
     one that actually works end-to-end.
3. Supabase gives you something like
   `postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres`
   - note the username is `postgres.[project-ref]`, not just `postgres`,
   for pooled connections. Change the scheme to `postgresql+asyncpg://`
   (this project's `DATABASE_URL` always needs that driver prefix - see
   `src/pulsequeue/core/config.py`):

   ```
   postgresql+asyncpg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres
   ```

   That's the value for `DATABASE_URL` below. Migrations run
   automatically on every Render deploy (see
   [`deploy/render/start.sh`](../deploy/render/start.sh)) - you don't
   need to run `alembic upgrade head` against Supabase yourself.

   **`[password]` is a placeholder - don't paste it with the brackets
   still on it.** And if your actual password contains any of
   `@ : / ? # % & + = space`, percent-encode it first (that `@` is
   exactly the character that normally separates the password from the
   host in this URL format - unencoded, it breaks the parsing in a way
   that looks like a DNS failure, not a credentials error):

   ```bash
   python3 -c "import urllib.parse; print(urllib.parse.quote('your-password', safe=''))"
   ```

## 2. Redis on Upstash

1. Create a database at [upstash.com](https://upstash.com) (free tier).
2. Copy the `rediss://` connection string (TLS; Upstash doesn't expose
   a plain `redis://` endpoint) from the database's dashboard - it
   looks like `rediss://default:[password]@[endpoint].upstash.io:6379`.
3. That's the value for `REDIS_URL`. Redis is optional in this
   project's design (ADR 0002) - if you'd rather not sign up for a
   third service, leave `REDIS_URL` unset; the app falls back to a
   default that will simply be unreachable in this deployment, and
   everything still works, just with the worker polling on its own
   schedule instead of an instant wake-up (logged as warnings, not
   errors).

## 3. Deploy to Render

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
4. Deploy. The service applies migrations, starts the API, and starts
   the in-process worker - all in this one step.
5. Visit `https://<your-service>.onrender.com/ui/` for the dashboard,
   or `https://<your-service>.onrender.com/docs` for the interactive
   API docs. Submit a task from the dashboard - it should move from
   `queued` to `succeeded` within a few seconds with no further setup.

**Free-tier cold starts**: Render's free web services sleep after ~15
minutes idle; the next request wakes it (expect a 30-60s delay on that
first request) - and since the worker lives in this same process, task
processing pauses while it's asleep too, resuming once the next
request wakes it. Fine for a portfolio demo, not for anything
latency-sensitive. `PULSEQUEUE_ALLOWED_ORIGINS` doesn't need to be set
for this deployment - the dashboard is served by the same API process
at the same origin, so no CORS configuration is needed between them.

## Alternative: a separate worker on a free GCP VM

If you'd rather the worker run as its own process - closer to this
project's actual documented architecture - and don't mind Google Cloud
requiring a card on file even for its free tier (it won't charge you
within the free limits, but some people would rather avoid giving a
card at all, which is exactly why the default path above doesn't need
one):

1. Set `PULSEQUEUE_RUN_WORKER_IN_PROCESS` to `false` (or remove it) on
   the Render service from step 3 above.
2. Google Cloud's "Always Free" tier includes one `e2-micro` instance
   (perpetually free, not a time-boxed trial) in `us-west1`,
   `us-central1`, or `us-east1`. In the GCP Console: Compute Engine →
   VM Instances → Create Instance.
   - Region: one of the three above (required for the free tier).
   - Machine type: `e2-micro`.
   - Boot disk: Ubuntu 24.04 LTS (ships Python 3.12, which this
     project's `requires-python = ">=3.11,<3.13"` accepts).
   - Leave firewall options unchecked - the worker only makes outbound
     connections (to Supabase and Upstash), it doesn't listen on any
     port.
3. SSH in (the Console's browser-based SSH button works, no local
   setup needed) and run:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/ayrus15/PulseQueue/main/deploy/gcp/setup.sh -o setup.sh
   bash setup.sh
   ```

4. The first run creates `/opt/pulsequeue/.env` with placeholder
   values and stops, telling you to edit it (`nano /opt/pulsequeue/.env`)
   with your real `DATABASE_URL`/`REDIS_URL` from steps 1-2 above.
5. Run `bash setup.sh` again. This time it installs
   [`deploy/gcp/pulsequeue-worker.service`](../deploy/gcp/pulsequeue-worker.service)
   as a systemd service, running as a dedicated unprivileged
   `pulsequeue` system user, and starts it.
6. Check it's actually running:

   ```bash
   sudo systemctl status pulsequeue-worker
   sudo journalctl -u pulsequeue-worker -f   # live logs
   ```

**Updating later**: `cd /opt/pulsequeue && git pull && .venv/bin/pip
install -e . && sudo systemctl restart pulsequeue-worker`.

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

## Things to verify yourself, not asserted here

- Google Cloud's free-tier terms, region availability, and whether
  your account still has Always Free eligibility (some promotional
  credits and the Always Free tier are different things) - check the
  GCP Console's billing page, only relevant if you take the GCP
  alternative above.
- Whether a `t2d`/`e2` family or region substitution is still called
  "Always Free" by the time you read this - cloud free tiers change
  faster than this doc will be kept in sync with them.
