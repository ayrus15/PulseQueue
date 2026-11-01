# Deploying to the cloud (Render + Supabase + Upstash)

A free-tier stack: Render runs the API (which also serves the
dashboard at `/ui`) and the worker from this repo's own `Dockerfile`;
Supabase provides PostgreSQL; Upstash provides Redis. Nothing here has
been deployed and verified end-to-end from this development machine
(no Docker, and no access to create third-party cloud accounts) - this
is a reviewed, best-effort guide, not a "confirmed working" claim. If
a step doesn't match what you see in these dashboards, their UIs
change; the connection-string shape and env var names below are the
part that actually matters and is stable.

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

   That's the value for `DATABASE_URL` below. Migrations run
   automatically on deploy (see `render.yaml`'s `dockerCommand`) - you
   don't need to run `alembic upgrade head` against Supabase yourself.

## 2. Redis on Upstash

1. Create a database at [upstash.com](https://upstash.com) (free tier).
2. Copy the `rediss://` connection string (TLS; Upstash doesn't expose
   a plain `redis://` endpoint) from the database's dashboard - it
   looks like `rediss://default:[password]@[endpoint].upstash.io:6379`.
3. That's the value for `REDIS_URL`. Redis is optional in this
   project's design (ADR 0002) - if you'd rather not sign up for a
   third service, leave `REDIS_URL` unset and the app falls back to
   the default `redis://localhost:6379/0` which will simply be
   unreachable in this deployment; everything still works, just with
   each worker polling instead of an instant wake-up (logged as
   warnings, not errors).

## 3. API + worker on Render

1. Push this repo to GitHub (already done if you're reading this from
   the repo itself).
2. Render dashboard → New → **Blueprint** → connect the repo. Render
   reads [`render.yaml`](../render.yaml) and proposes two services:
   `pulsequeue-api` (web) and `pulsequeue-worker` (background worker).
3. For **both** services, fill in:
   - `DATABASE_URL` - the Supabase connection string from step 1.
   - `REDIS_URL` - the Upstash connection string from step 2 (or leave
     unset per the note above).
4. For `pulsequeue-api` only, also set:
   - `PULSEQUEUE_ADMIN_TOKEN` - a real random value, not the repo's
     `change-me-locally` default. This gates the dead-letter
     listing/requeue endpoints and the dashboard's dead-letter panel.
5. Deploy. The API applies migrations on boot, then starts; the worker
   starts independently and begins polling.
6. Visit `https://<your-service>.onrender.com/ui/` for the dashboard,
   or `https://<your-service>.onrender.com/docs` for the interactive
   API docs.

### Things to verify yourself, not asserted here

- **Whether Render's free tier currently includes Background Worker
  services.** It has historically required a paid plan on some Render
  pricing iterations; pricing pages change over time and this wasn't
  verified against a real account from this session. If the free tier
  doesn't cover it, either upgrade that one service (~a few dollars a
  month) or run the worker somewhere else (Railway's usage-based free
  credit, or even your own machine pointed at the same Supabase/Upstash
  URLs via `.env`) while keeping the API on Render.
- **Free-tier cold starts.** Render's free web services sleep after
  ~15 minutes idle; the next request wakes it (expect a 30-60s delay
  on that first request). Fine for a portfolio demo, not for anything
  latency-sensitive.
- `PULSEQUEUE_ALLOWED_ORIGINS` doesn't need to be set for this
  deployment - the dashboard is served by the same API process at the
  same origin, so no CORS configuration is needed between them.
