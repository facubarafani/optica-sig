# Deploy — SGI Óptica (free, self-hosted, future-proof)

This guide deploys the app **free, always-on, with full control and no lock-in**:
an **Oracle Cloud Always Free** ARM VM running **Coolify** (open-source PaaS),
which deploys the app container + a one-click **PostgreSQL** and issues
**automatic HTTPS**.

```
Oracle Cloud Always Free VM (ARM Ampere A1, Santiago/São Paulo region)
└─ Coolify  (open-source, self-hosted — Heroku-style deploys)
     ├─ FastAPI container  ← built from this repo's Dockerfile  (auto HTTPS via Traefik)
     └─ PostgreSQL         ← one-click, on the same private network, auto-backups
```

Why this stack: it costs **$0** forever, you have **root-level control**, and the
**future-proofing comes from the architecture, not the vendor** — the app is a
portable Docker image + plain Postgres managed by an open-source PaaS, so if
Oracle ever disappoints you, you lift-and-shift the *same* setup to Hetzner
(~$5/mo) or convert Oracle to pay-as-you-go in minutes. See **Escalation** below.

> Container artifacts in this repo: `Dockerfile`, `docker/entrypoint.sh`
> (runs `alembic upgrade head` → optional seed → uvicorn), `docker-compose.prod.yml`
> + `docker/Caddyfile` (the portable any-VM path), `.env.prod.example`.

---

## 0. Prerequisites

- A **GitHub/GitLab repo** with this code (Coolify deploys from Git). Public is
  fine; private needs a deploy key (Coolify guides you).
- A **domain** (or subdomain, e.g. `demo.tudominio.com`) you can edit DNS for —
  required for a real HTTPS certificate.
- ~30–45 min the first time (most of it is Oracle's signup).

---

## 1. Create the Oracle Always Free VM

1. Sign up at <https://signup.oraclecloud.com>. **Pick your home region carefully —
   it's permanent.** For Argentina latency choose **Chile (Santiago)** or
   **Brazil (São Paulo / Vinhedo)**. Use a **Visa credit card** (debit/other
   often fails — a known signup quirk).
2. **Compute → Instances → Create instance**:
   - **Image**: Ubuntu 22.04 (or 24.04).
   - **Shape**: change to **Ampere (ARM) → VM.Standard.A1.Flex**, set
     **2 OCPU / 12 GB RAM** (the current Always Free allotment). If you see
     *"out of capacity"*, retry later or try another availability domain — ARM
     capacity is often tight.
   - Add your **SSH public key**.
   - Create. Note the **public IP**.
3. **Open the firewall in BOTH places** (the #1 "site unreachable" gotcha):
   - **OCI Security List** (VCN → Subnet → Security List): add ingress rules for
     TCP **80**, **443**, and **8000** (Coolify UI) from `0.0.0.0/0`.
   - **On the VM** (SSH in): allow them at the OS level too:
     ```bash
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
     sudo netfilter-persistent save   # persists across reboot
     ```
4. **Strongly recommended: upgrade the tenancy to Pay-As-You-Go.** You stay **$0
   within the Always Free limits**, but PAYG instances are **exempt from idle
   reclamation** (a free-only box can be stopped if it looks idle for 7 days) and
   it unlocks instant resizing later. Account → Upgrade to Paid.

---

## 2. Point your domain at the VM

Create a DNS **A record**: `demo.tudominio.com → <VM public IP>`. Wait for it to
resolve (`ping demo.tudominio.com`). HTTPS won't issue until DNS is live.

---

## 3. Install Coolify

SSH into the VM and run the official installer:

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```

Then open **`http://<VM public IP>:8000`**, create the admin account, and (in
Settings) set Coolify's own FQDN if you want the dashboard on HTTPS too. The
2 OCPU / 12 GB box runs Coolify + app + Postgres comfortably.

---

## 4. Add PostgreSQL (one-click)

1. Coolify → **Projects → New Project** (e.g. `sgi`) → an Environment.
2. **+ New → Database → PostgreSQL 16**. Create it.
3. Copy its **internal connection URL** (the `*-internal`/service-name one, not
   the public one). You'll convert the scheme in the next step.

---

## 5. Deploy the app

1. In the same project: **+ New → Application → Public Repository** (or your
   private repo) → paste the repo URL → **Build Pack: Dockerfile**.
2. **Port**: `8000`. **Health check path**: `/health`.
3. **Domain**: `https://demo.tudominio.com` (Coolify's Traefik auto-issues
   Let's Encrypt TLS).
4. **Environment variables** (Coolify → the app → Environment):
   ```
   DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST:5432/DBNAME   # from step 4
   SECRET_KEY=<run: openssl rand -hex 32>
   SEED_ON_START=true        # FIRST deploy only — flip to false afterwards
   ACCESS_TOKEN_EXPIRE_MINUTES=480
   DEFAULT_COMPANY_ID=1
   WEB_CONCURRENCY=2
   ```
   > ⚠️ Take the Postgres URL from step 4 and make sure the scheme is
   > **`postgresql+psycopg2://`** (Coolify usually gives `postgres://...` — just
   > replace the prefix). Use the **internal** host so the app and DB talk over
   > the private network.
5. **Deploy.** The container's entrypoint runs `alembic upgrade head`, seeds the
   demo data (because `SEED_ON_START=true`), then starts uvicorn.

---

## 6. Verify & harden

1. Open **`https://demo.tudominio.com/app`** → log in with the seeded
   `admin@sgi.com` / `admin1234`. Send that link to your partner. ✅
2. **Immediately after the first successful boot:**
   - Set **`SEED_ON_START=false`** and redeploy (so the seed never re-runs).
   - In the UI (**Usuarios y Roles**) create a real admin user and **deactivate
     or change** the demo `admin@sgi.com` account.
   - Confirm `SECRET_KEY` is your generated value, not the default.
   - Restrict Coolify's dashboard: close port **8000** to the public again, or
     put it behind Coolify's own domain + auth, and keep Coolify updated.
3. **Backups**: Coolify → the Postgres resource → **Backups** → schedule daily
   dumps to an S3-compatible bucket (Oracle Object Storage has 20 GB free, or
   Backblaze B2). Don't rely on VM snapshots alone.

---

## Escalation (when the free box isn't enough)

All lateral — **no rewrite**, because everything is Docker + plain Postgres:

| Need | Move |
|---|---|
| More CPU/RAM, same host | Oracle is already PAYG → resize the A1.Flex shape (reboot only); pay only for resources above the free baseline. |
| A different host / leave Oracle | Provision a **Hetzner CAX11** (~€5/mo, 2 vCPU/4 GB, full root), install Coolify the same way (§3), point DNS, deploy the same repo. Closest region to AR: Ashburn (VA). |
| Offload the database | Create a free **Neon** Postgres (São Paulo region), change `DATABASE_URL` to its connection string, redeploy. Escalates to paid Neon (~$19/mo) with no code change. |

---

## Alternative: plain `docker compose` on any VM (no Coolify)

For a bare Hetzner/Oracle VM without Coolify, this repo ships a self-contained
stack (`docker-compose.prod.yml` = app + Postgres + Caddy auto-HTTPS):

```bash
git clone <repo> && cd sig-optica
cp .env.prod.example .env     # set SECRET_KEY, POSTGRES_PASSWORD, APP_DOMAIN
docker compose -f docker-compose.prod.yml up -d --build
```

Point `APP_DOMAIN`'s DNS A record at the server first; Caddy fetches the TLS cert
automatically. App is then live at `https://$APP_DOMAIN/app`.

---

## Updating the app later

- **Coolify**: push to the repo → click **Redeploy** (or enable auto-deploy on
  push). Migrations run automatically on each boot via the entrypoint.
- **Compose**: `git pull && docker compose -f docker-compose.prod.yml up -d --build`.
