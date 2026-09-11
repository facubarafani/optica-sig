"""Manage provider (platform) accounts — the logins for the /admin console.

    python -m scripts.platform_admin list
    python -m scripts.platform_admin create
    python -m scripts.platform_admin password owner@sgi.com
    python -m scripts.platform_admin disable ex@sgi.com

Deliberately a CLI and not an API endpoint. A platform account can enter any
customer's data, so the right authorisation for minting one is *shell access to
the server*, not a form — there is no endpoint to attack, no bootstrap
chicken-and-egg, and no path from a compromised provider session to creating
more provider accounts.

Passwords are never taken as a command-line flag: argv shows up in ``ps`` and
in shell history. Type it at the prompt, or pipe it in with ``--password-stdin``.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.core.database import SessionLocal
from app.services import platform as platform_service


def _fail(msg: str) -> None:
    print(f"✖ {msg}", file=sys.stderr)
    raise SystemExit(1)


def _read_password(from_stdin: bool, prompt: str = "Contraseña") -> str:
    """Prompt twice, or read a single line from stdin for automation."""
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            _fail("No llegó ninguna contraseña por stdin.")
        return password
    if not sys.stdin.isatty():
        _fail("Sin terminal interactiva. Usá --password-stdin.")
    password = getpass.getpass(f"{prompt}: ")
    if password != getpass.getpass("Repetir: "):
        _fail("Las contraseñas no coinciden.")
    return password


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    if not value and default:
        return default
    if not value:
        _fail(f"{label} es obligatorio.")
    return value


# --- commands -------------------------------------------------------------
def cmd_list(args) -> None:
    db = SessionLocal()
    try:
        users = platform_service.list_platform_users(db)
        if not users:
            print("No hay cuentas de plataforma. Creá una con:")
            print("  python -m scripts.platform_admin create")
            return
        print(f"{'ID':<4} {'EMAIL':<32} {'NOMBRE':<22} {'ESTADO':<10} ÚLTIMO INGRESO")
        for u in users:
            last = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "nunca"
            state = "activo" if u.is_active else "desactivado"
            print(f"{u.id:<4} {u.email:<32} {u.full_name:<22} {state:<10} {last}")

        # A known default in a live deployment is the one thing worth shouting
        # about: this account can enter every customer's data.
        weak = [
            u for u in users
            if u.is_active
            and any(
                platform_service.verify_password(d, u.hashed_password)
                for d in platform_service.INSECURE_DEFAULTS
            )
        ]
        if weak:
            print()
            print("⚠  Estas cuentas siguen con una contraseña por defecto:")
            for u in weak:
                print(f"     {u.email}  →  python -m scripts.platform_admin password {u.email}")
    finally:
        db.close()


def cmd_create(args) -> None:
    db = SessionLocal()
    try:
        email = args.email or _prompt("Email")
        if platform_service.get_platform_user(db, email):
            _fail(f"Ya existe una cuenta de plataforma para {email}.")
        full_name = args.name or _prompt("Nombre completo")
        password = _read_password(args.password_stdin)
        try:
            user = platform_service.create_platform_user(
                db, email=email, full_name=full_name, password=password
            )
        except platform_service.PlatformError as exc:
            _fail(str(exc))
        print(f"✅ Cuenta de plataforma creada: {user.email} (id={user.id})")
        print("   Ingresá en /admin con ese email.")
    finally:
        db.close()


def cmd_password(args) -> None:
    db = SessionLocal()
    try:
        user = platform_service.get_platform_user(db, args.email)
        if user is None:
            _fail(f"No existe una cuenta de plataforma para {args.email}.")
        password = _read_password(args.password_stdin, "Nueva contraseña")
        try:
            platform_service.set_platform_password(db, user, password)
        except platform_service.PlatformError as exc:
            _fail(str(exc))
        print(f"✅ Contraseña actualizada para {user.email}.")
    finally:
        db.close()


def _set_active(email: str, active: bool) -> None:
    db = SessionLocal()
    try:
        user = platform_service.get_platform_user(db, email)
        if user is None:
            _fail(f"No existe una cuenta de plataforma para {email}.")
        if not active:
            others = [
                u for u in platform_service.list_platform_users(db)
                if u.is_active and u.id != user.id
            ]
            if not others:
                _fail(
                    "Es la única cuenta activa — desactivarla te deja sin acceso "
                    "a /admin. Creá otra primero."
                )
        platform_service.set_platform_active(db, user, active)
        print(f"✅ {user.email} quedó {'activa' if active else 'desactivada'}.")
    finally:
        db.close()


def cmd_disable(args) -> None:
    _set_active(args.email, False)


def cmd_enable(args) -> None:
    _set_active(args.email, True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.platform_admin",
        description="Cuentas del proveedor para la consola /admin.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="listar cuentas de plataforma")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("create", help="crear una cuenta de plataforma")
    p.add_argument("--email")
    p.add_argument("--name")
    p.add_argument(
        "--password-stdin", action="store_true",
        help="leer la contraseña de stdin en vez de pedirla (para scripts)",
    )
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("password", help="cambiar la contraseña de una cuenta")
    p.add_argument("email")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=cmd_password)

    p = sub.add_parser("disable", help="desactivar una cuenta")
    p.add_argument("email")
    p.set_defaults(func=cmd_disable)

    p = sub.add_parser("enable", help="reactivar una cuenta")
    p.add_argument("email")
    p.set_defaults(func=cmd_enable)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
