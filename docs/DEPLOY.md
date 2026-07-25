# Deploy — SGI Óptica

The app is a portable **Docker image + PostgreSQL**, so the host is a swappable
detail: switching later is just *"change `DATABASE_URL` / redeploy the same
image."* Pick a tier:

| Tier | Stack | Cost | Use when |
|---|---|---|---|
| **Quick (now)** | **Render + Neon** | $0 | Get a demo live today, zero servers to manage |
| **Long-term** ⭐ | **Hetzner + Coolify** | ~€5/mo | Real usage — max control + reliable, no free-tier surprises |
| Free-forever | Oracle Always Free + Coolify | $0 | $0 is non-negotiable (accept the volatility — see caveats) |
| Portable | `docker-compose` on any VM | varies | Total DIY / lift-and-shift |

> Repo: `https://github.com/facubarafani/optica-sig`
> Container artifacts in this repo: `Dockerfile`, `docker/entrypoint.sh`
> (runs `alembic upgrade head` → optional seed → uvicorn), `render.yaml` (Render
> blueprint), `docker-compose.prod.yml` + `docker/Caddyfile` (any-VM path),
> `.env.prod.example`.

**Prerequisites (all paths):** the repo on GitHub (done), and a **domain** you
control if you want a custom HTTPS hostname (the Render path also gives you a free
`*.onrender.com` URL with no domain needed).

---

## Quick start (now): Render + Neon

Easiest free + **persistent** path. Render runs the Docker image (free, auto
HTTPS); Neon holds the data (free Postgres that doesn't expire or pause —
Render's own free Postgres self-deletes after 30 days, which is why the DB lives
on Neon). ~10 minutes, no servers.

### 1. Free Postgres on Neon (~3 min)
1. Sign up at <https://neon.tech> (no card).
2. New project → Postgres 16 → **region: AWS US East (N. Virginia / us-east-1)**.
   Co-locate it with Render's Virginia region (below): the app queries the DB on
   every request, so app↔DB proximity matters more than DB↔Argentina. (For the
   self-hosted VM paths where the app lives in São Paulo/Santiago, pick a South
   America Neon region instead.)
3. Copy the **connection string**, e.g.
   `postgresql://user:pass@ep-xxx.sa-east-1.aws.neon.tech/dbname?sslmode=require`
4. Change the scheme to **`postgresql+psycopg2://`** (edit the prefix only); keep
   `?sslmode=require`. This is your `DATABASE_URL`.

### 2. Deploy on Render (~5 min)
**Option A — Blueprint (one-click, uses `render.yaml`):**
Render → **New → Blueprint** → pick this repo. It creates the web service from
`render.yaml` and prompts for `DATABASE_URL` (paste the Neon string from step 1).
`SECRET_KEY` is auto-generated. Deploy. *(Requires `render.yaml` to be on the
GitHub default branch.)*

**Option B — Manual:**
Render → **New → Web Service** → pick the repo (it detects the Dockerfile) →
Region **Virginia**, Instance type **Free**, Health Check Path **`/health`**,
then set env vars:
```
DATABASE_URL    = <Neon string, postgresql+psycopg2://…?sslmode=require>
SECRET_KEY      = <openssl rand -hex 32>
SEED_ON_START   = true
WEB_CONCURRENCY = 1
ACCESS_TOKEN_EXPIRE_MINUTES = 480
DEFAULT_COMPANY_ID = 1
```
Create. The container migrates the DB, seeds demo data, then serves on Render's
`$PORT` (the Dockerfile already honors it).

### 3. Verify & tidy
1. Open **`https://<your-app>.onrender.com/app`** → log in with
   `admin@sgi.com` / `admin1234`. That's the partner link. ✅
2. Then set **`SEED_ON_START=false`** (redeploys) and change the demo admin
   password in **Usuarios y Roles**.

**Quirk:** Render's *free* web service sleeps after ~15 min idle → first hit after
a quiet spell takes ~30–60 s to wake. Fine for a demo; warm it up before a
meeting, or keep it awake with a free UptimeRobot ping every ~10 min.

---

## Long-term home: Hetzner + Coolify  ⭐

When the demo becomes real, this is the recommended long-term host: the **same**
Coolify + Docker + Postgres setup as the Oracle path, but on a **paid, predictable,
well-regarded** VM — no free-tier rug-pulls, no ARM capacity lottery, no idle
reclamation, and the best price/performance VPS available. You keep full
root-level control and zero lock-in.

```
Hetzner VM (CAX11, ~€5/mo, Ashburn VA)
└─ Coolify (open-source, self-hosted — Heroku-style deploys)
     ├─ FastAPI container  ← this repo's Dockerfile  (auto HTTPS via Traefik)
     └─ PostgreSQL         ← one-click, private network, scheduled backups
```

### 1. Provision the VM
1. <https://hetzner.com/cloud> → new project → **Add Server**.
   - **Location: Ashburn, VA (US East)** — closest of Hetzner's regions to
     Argentina (~120–160 ms; fine for an admin/ERP app). EU is ~200 ms+.
   - Image: Ubuntu 24.04.
   - Type: **CAX11** (Arm Ampere, 2 vCPU / 4 GB / 40 GB NVMe, ~€4.49/mo) — ample
     for this app; add an IPv4 (~€0.50/mo). *(Prefer x86? choose CX23 — our image
     is multi-arch, so either works.)*
   - Add your SSH key → Create.
2. **Firewall:** enable the Hetzner Cloud Firewall and allow TCP **22/80/443** —
   one place, no OS-level iptables dance (a nicety over Oracle).
3. **DNS:** point your domain's **A record** at the server's IP; wait for it to
   resolve (`ping yourdomain`).

### 2. Then follow the shared Coolify steps
Continue with **[Install Coolify → Add Postgres → Deploy → Verify & harden]** in
the *Coolify steps* section below — they are identical regardless of VM host.

### Scaling later
In-place resize CAX11 → CAX21 (4 vCPU / 8 GB) → … (reboot only), add a Volume for
storage, or offload the DB to managed Neon by changing `DATABASE_URL`. All
lateral, no rewrite.

---

## Free-forever: Oracle Cloud Always Free + Coolify

Genuinely $0 forever (a real always-on ARM VM), but accept the volatility:
Oracle **silently halved** the free ARM allotment in June 2026, ARM capacity is
often *"out of capacity,"* idle free instances can be reclaimed, and free-account
suspensions are common. Mitigate by upgrading to Pay-As-You-Go (stays $0 within
free limits). Use this only if free is non-negotiable; otherwise prefer Hetzner.

### 1. Provision the VM
1. Sign up at <https://signup.oraclecloud.com>. **Home region is permanent** —
   choose **Chile (Santiago)** or **Brazil (São Paulo)** for AR latency. Use a
   **Visa credit card** (debit often fails at signup).
2. **Right after signup, upgrade the tenancy to Pay-As-You-Go** (still $0 within
   free limits) — exempts the VM from idle reclamation and unlocks resizing.
3. **Compute → Instances → Create instance**: Ubuntu 24.04, shape
   **VM.Standard.A1.Flex** at **2 OCPU / 12 GB** (current free allotment; retry
   if *"out of capacity"*). Add SSH key. Note the public IP.
4. **Open the firewall in BOTH places** (the #1 "unreachable" gotcha):
   - **OCI Security List** (VCN → subnet → Security List): ingress TCP **80, 443,
     8000** from `0.0.0.0/0`.
   - **On the VM** (OS firewall):
     ```bash
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80   -j ACCEPT
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443  -j ACCEPT
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
     sudo netfilter-persistent save
     ```
5. **DNS:** point your domain's **A record** at the public IP.

### 2. Then follow the shared Coolify steps below.

---

## Coolify steps (shared by the Hetzner & Oracle paths)

Run these on the VM after it's provisioned, the firewall is open, and DNS points
at it.

### Install Coolify
```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```
Open **`http://<VM_IP>:8000`**, create the admin account, finish onboarding.

### Add PostgreSQL (one-click)
Coolify → **+ New → Project** (`sgi`) → Environment → **+ New → Database →
PostgreSQL 16** → Create. Copy its **internal** connection URL.

### Deploy the app
1. Same project → **+ New → Application → Public Repository** → paste the repo →
   **Build Pack: Dockerfile**, branch `main`.
2. **Port = `8000`**, **Health check path = `/health`**, **Domain =
   `https://yourdomain`** (Coolify's Traefik auto-issues Let's Encrypt TLS).
3. **Environment variables:**
   ```
   DATABASE_URL = postgresql+psycopg2://USER:PASS@HOST:5432/DBNAME   # from above
   SECRET_KEY   = <openssl rand -hex 32>
   SEED_ON_START = true        # first deploy only — then flip to false
   ACCESS_TOKEN_EXPIRE_MINUTES = 480
   DEFAULT_COMPANY_ID = 1
   WEB_CONCURRENCY = 2
   ```
   > ⚠️ Coolify usually gives `postgres://…`; change the scheme to
   > **`postgresql+psycopg2://`** and use the **internal** host so app↔DB stay on
   > the private network.
4. **Deploy.** The entrypoint runs `alembic upgrade head` → seed → uvicorn.

### Verify & harden
1. Open **`https://yourdomain/app`** → log in `admin@sgi.com` / `admin1234`. ✅
2. Set **`SEED_ON_START=false`** + redeploy; create a real admin and
   deactivate/change the demo account; confirm `SECRET_KEY` is your value.
3. Lock down Coolify's dashboard (restrict port 8000 / put it behind its own
   domain + auth) and keep Coolify updated.
4. **Backups:** Coolify → Postgres resource → **Backups** → daily dump to
   S3-compatible storage (Oracle Object Storage 20 GB free, or Backblaze B2).

---

## Portable: `docker compose` on any VM (no Coolify)

For a bare VM without Coolify, this repo ships a self-contained stack
(`docker-compose.prod.yml` = app + Postgres + Caddy auto-HTTPS):
```bash
git clone https://github.com/facubarafani/optica-sig && cd optica-sig
cp .env.prod.example .env     # set SECRET_KEY, POSTGRES_PASSWORD, APP_DOMAIN
docker compose -f docker-compose.prod.yml up -d --build
```
Point `APP_DOMAIN`'s DNS A record at the server first; Caddy fetches the TLS cert
automatically. Live at `https://$APP_DOMAIN/app`.

---

## Updating the app later

- **Render**: push to `main` → auto-deploys (or click Manual Deploy).
- **Coolify**: push to `main` → **Redeploy** (or enable auto-deploy on push).
- **Compose**: `git pull && docker compose -f docker-compose.prod.yml up -d --build`.

Migrations run automatically on every boot via the container entrypoint.
