"""Check the DNS for miopticadigital.com.ar, step by step.

    python -m scripts.check_dns

Run it after each change while setting the domain up. It reports what is in
place, what is missing, and what to do next — so propagation is something you
watch rather than guess at.

Shells out to ``dig`` rather than adding a DNS library: dig ships with macOS
and every Linux, and this is a diagnostic, not application code.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from app.core.config import settings

DOMAIN = "miopticadigital.com.ar"
APP_HOST = "app." + DOMAIN
RENDER_HOST = "sgi-optica.onrender.com"

# Resend puts SPF and the bounce MX on a sending subdomain rather than the
# apex, so the shop's normal mail (if any) is never affected by ours. DKIM
# goes at resend._domainkey on the apex.
SEND_HOST = "send." + DOMAIN
DKIM_HOST = "resend._domainkey." + DOMAIN

OK, MISSING, WARN = "✅", "❌", "⚠️ "


# Ask a public resolver rather than whatever the machine is configured to use.
# While a domain is being set up it has usually just returned NXDOMAIN, and the
# negative answer is cached for the zone's minimum TTL — 2 hours for .com.ar.
# A checker that reports stale "no todavía" for two hours after the change
# landed is worse than no checker, because it sends you back to the panel to
# fix something that was never broken.
RESOLVER = "1.1.1.1"


def dig(name: str, rrtype: str) -> list[str]:
    try:
        out = subprocess.run(
            ["dig", "+short", "+time=3", "+tries=2", f"@{RESOLVER}", rrtype, name],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def txt(name: str) -> list[str]:
    """TXT values, unquoted and rejoined (long records arrive split)."""
    values = []
    for raw in dig(name, "TXT"):
        parts = [p for p in raw.split('" "')]
        values.append("".join(parts).strip('"'))
    return values


def step(n: int, title: str) -> None:
    print(f"\n{n}. {title}")
    print("   " + "-" * (len(title) + 2))


def main() -> int:
    if not shutil.which("dig"):
        print("Necesito 'dig' (viene con macOS y con dnsutils en Linux).")
        return 2

    print(f"Revisando {DOMAIN}  (resolver {RESOLVER})\n" + "=" * (25 + len(DOMAIN)))
    todo: list[str] = []

    # --- 1. delegation ---------------------------------------------------
    step(1, "Delegación de nameservers (nic.ar → Cloudflare)")
    ns = dig(DOMAIN, "NS")
    if not ns:
        print(f"   {MISSING} El dominio no resuelve todavía: no hay nameservers.")
        print("      En nic.ar → Delegaciones → crear una con los NS de Cloudflare")
        print("      y asignarla al dominio.")
        todo.append("Delegar los nameservers a Cloudflare en nic.ar")
    else:
        on_cf = any("cloudflare" in n.lower() for n in ns)
        print(f"   {OK if on_cf else WARN} Nameservers: {', '.join(ns)}")
        if not on_cf:
            print("      No parecen de Cloudflare. Si usás el DNS de nic.ar está bien,")
            print("      pero cargá los TXT largos (DKIM) con cuidado.")

    # --- 2. mail (Resend) ------------------------------------------------
    step(2, "Correo (Resend): SPF, DKIM, MX y DMARC")

    spf = [v for v in txt(SEND_HOST) if v.lower().startswith("v=spf1")]
    if spf:
        print(f"   {OK} SPF en {SEND_HOST}: {spf[0]}")
    else:
        print(f"   {MISSING} Falta el SPF: TXT en 'send' → v=spf1 include:amazonses.com ~all")
        todo.append("Cargar el SPF de Resend (TXT en 'send')")

    mx = dig(SEND_HOST, "MX")
    if mx:
        print(f"   {OK} MX en {SEND_HOST}: {mx[0]}")
    else:
        print(f"   {MISSING} Falta el MX de rebotes: MX en 'send' → feedback-smtp...amazonses.com")
        todo.append("Cargar el MX de Resend (MX en 'send')")

    if txt(DKIM_HOST):
        print(f"   {OK} DKIM en {DKIM_HOST}")
    else:
        print(f"   {MISSING} Falta el DKIM: TXT en 'resend._domainkey'")
        print("      Resend da el valor exacto al agregar el dominio.")
        todo.append("Cargar el DKIM de Resend (TXT en 'resend._domainkey')")

    dmarc = [v for v in txt(f"_dmarc.{DOMAIN}") if v.lower().startswith("v=dmarc1")]
    if dmarc:
        print(f"   {OK} DMARC: {dmarc[0]}")
    else:
        print(f"   {MISSING} Falta el DMARC (TXT en '_dmarc') — opcional pero recomendado.")
        print(f'      Para arrancar: "v=DMARC1; p=none; rua=mailto:facu@{DOMAIN}"')
        todo.append("Cargar el DMARC")

    # --- 3. the app ------------------------------------------------------
    step(3, f"La app en {APP_HOST}")
    cname = dig(APP_HOST, "CNAME")
    addr = dig(APP_HOST, "A")
    if cname or addr:
        target = cname[0].rstrip(".") if cname else f"A {addr[0]}"
        good = RENDER_HOST in (cname[0] if cname else "")
        print(f"   {OK if good else WARN} {APP_HOST} → {target}")
        if not good and cname:
            print(f"      Se esperaba un CNAME a {RENDER_HOST}.")
        if addr and not cname:
            print("      Hay un A en vez de un CNAME. Si es una IP de Cloudflare,")
            print("      el proxy está activado (nube naranja): ponelo en 'DNS only',")
            print("      o Render no puede emitir el certificado.")
    else:
        print(f"   {MISSING} {APP_HOST} no resuelve.")
        print(f"      Cloudflare: CNAME 'app' → {RENDER_HOST}, en DNS only (nube gris).")
        todo.append(f"Crear el CNAME de {APP_HOST} y agregarlo en Render")

    # --- 4. the deployed app --------------------------------------------
    step(4, "El despliegue")
    health = None
    url = f"https://{APP_HOST}/health"
    try:
        # Render's free tier sleeps; a cold start takes the better part of a
        # minute, which is a slow answer rather than a broken one.
        with urllib.request.urlopen(url, timeout=90) as resp:
            health = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        print(f"   {MISSING} {url} no responde ({exc}).")
        todo.append(f"Revisar que Render sirva {APP_HOST}")
    if health:
        print(f"   {OK} {url} responde — entorno '{health.get('environment')}'")
        if health.get("environment") == "local":
            print("      Render debería tener ENVIRONMENT=production.")
            todo.append("Poner ENVIRONMENT=production en Render")

    # --- 5. local config, for information ---------------------------------
    # Deliberately not warnings: console + localhost is *correct* on a laptop.
    # An earlier version nagged about them here, which made a clean setup look
    # broken every time it was run locally.
    step(5, "Tu configuración local (informativo)")
    print(f"   ·  EMAIL_BACKEND    = {settings.email_backend}")
    print(f"   ·  PUBLIC_BASE_URL  = {settings.public_base_url}")
    print(f"   ·  EMAIL_FROM       = {settings.email_from}")
    if settings.email_backend in ("console", "memory"):
        print("      (console no manda nada — está bien acá)")

    print("\n   En Render, en cambio, tiene que estar:")
    print("      EMAIL_BACKEND    = resend")
    print("      RESEND_API_KEY   = re_…")
    print(f"      PUBLIC_BASE_URL  = https://{APP_HOST}")
    print(f"      EMAIL_FROM       = {settings.email_from}")
    print("   Esto no se puede verificar desde acá: miralo en el panel de Render.")

    # --- summary ---------------------------------------------------------
    print("\n" + "=" * 46)
    if todo:
        print("Falta:")
        for i, item in enumerate(todo, 1):
            print(f"  {i}. {item}")
        print("\nLos cambios de DNS pueden tardar. Volvé a correr esto en un rato.")
    else:
        print("DNS y despliegue en orden. 🎉")
        print("Queda confirmar en Render las variables de arriba, y mandarte")
        print("una prueba real:")
        print("  EMAIL_BACKEND=resend RESEND_API_KEY=re_… \\")
        print("    python -m scripts.send_test_email vos@gmail.com")
    return 0


if __name__ == "__main__":
    sys.exit(main())
