"""Provider-side operations: who we are, what we did, and to which tenant.

Everything here crosses the ``company_id`` boundary that the rest of the
codebase is built to respect. That is the whole point of the module, and the
reason it is the only one allowed to: keeping cross-tenant reads in one file
means there is one place to audit when asking "what can reach another shop's
data?".
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import (
    SCOPE_TENANT,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.auth import User
from app.models.company import Company
from app.models.enums import PlatformAction
from app.models.invoicing import ArcaIssuer, Invoice, InvoicingRequest
from app.models.platform import PlatformAuditLog, PlatformUser
from app.models.product import Product
from app.models.sales import Sale
from app.schemas.invoicing import FiscalData, TenantInvoicingLink, TenantInvoicingUpdate
from app.core.config import settings
from app.services import arca, email, email_templates, invitations, provisioning

# An impersonation token is a key to someone else's shop. It expires in half an
# hour regardless of the configured session length, so a forgotten support tab
# is not a standing door.
IMPERSONATION_MINUTES = 30

# Longer than the 8 a shop user needs. A provider account can enter any
# tenant's data, so it is the highest-value credential in the system and is
# typed by hand a handful of times ever.
MIN_PLATFORM_PASSWORD = 12

# The config defaults. Fine for a local demo, never for a real deployment —
# the seed refuses them outside `local` rather than silently publishing a
# known password for an account that can reach every customer.
INSECURE_DEFAULTS = {"owner1234", "change-me", "admin1234"}


class PlatformError(Exception):
    """Raised on provider-side rule violations."""


# --- identity -------------------------------------------------------------
def authenticate(db: Session, email: str, password: str) -> PlatformUser | None:
    user = db.execute(
        select(PlatformUser).where(PlatformUser.email == email.strip().lower())
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return user


def validate_password(password: str) -> None:
    """One policy, wherever a provider password is set."""
    # Known defaults first: every one of them is also too short, so checking
    # length first would make this branch unreachable and report the wrong
    # reason for the one mistake people actually make — pasting the demo
    # password into a real deployment.
    if password in INSECURE_DEFAULTS:
        raise PlatformError(
            "Esa es la contraseña de demo del repositorio. Elegí otra."
        )
    if len(password or "") < MIN_PLATFORM_PASSWORD:
        raise PlatformError(
            f"La contraseña debe tener al menos {MIN_PLATFORM_PASSWORD} caracteres."
        )


def get_platform_user(db: Session, email: str) -> PlatformUser | None:
    return db.execute(
        select(PlatformUser).where(PlatformUser.email == email.strip().lower())
    ).scalar_one_or_none()


def list_platform_users(db: Session) -> list[PlatformUser]:
    return list(
        db.execute(select(PlatformUser).order_by(PlatformUser.id)).scalars().all()
    )


def set_platform_password(db: Session, user: PlatformUser, password: str) -> PlatformUser:
    validate_password(password)
    user.hashed_password = hash_password(password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def set_platform_active(
    db: Session, user: PlatformUser, active: bool
) -> PlatformUser:
    """Disable rather than delete: the audit log points at these rows."""
    user.is_active = active
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_platform_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    commit: bool = True,
    validate: bool = True,
) -> PlatformUser:
    """Create a provider account.

    ``validate=False`` exists for exactly one caller: the local demo seed,
    which deliberately plants a well-known password so ``/admin`` is one copy
    and paste away. It checks ``ENVIRONMENT == local`` immediately before
    asking, so the opt-out is visible at the call site rather than being a
    hole in the policy.
    """
    if validate:
        validate_password(password)
    email = email.strip().lower()
    existing = db.execute(
        select(PlatformUser).where(PlatformUser.email == email)
    ).scalar_one_or_none()
    if existing:
        raise PlatformError(f"Ya existe un usuario de plataforma con el email {email}.")
    user = PlatformUser(
        email=email, full_name=full_name, hashed_password=hash_password(password)
    )
    db.add(user)
    if commit:
        db.commit()
        db.refresh(user)
    else:
        db.flush()
    return user


# --- audit ----------------------------------------------------------------
def record(
    db: Session,
    platform_user: PlatformUser,
    action: PlatformAction,
    *,
    company_id: int | None = None,
    target_user_id: int | None = None,
    detail: str | None = None,
    commit: bool = True,
) -> PlatformAuditLog:
    """Write down what a provider user did.

    Callers that mint an impersonation token must call this *before* handing
    the token over, so a crash between the two leaves evidence of the attempt
    rather than silent access.
    """
    entry = PlatformAuditLog(
        platform_user_id=platform_user.id,
        action=action.value,
        company_id=company_id,
        target_user_id=target_user_id,
        detail=(detail or None) and detail[:500],
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    else:
        db.flush()
    return entry


def list_audit(
    db: Session, *, company_id: int | None = None, limit: int = 100
) -> list[PlatformAuditLog]:
    stmt = select(PlatformAuditLog).order_by(PlatformAuditLog.id.desc()).limit(limit)
    if company_id is not None:
        stmt = stmt.where(PlatformAuditLog.company_id == company_id)
    return list(db.execute(stmt).scalars().all())


# --- tenants --------------------------------------------------------------
def _count_by_company(db: Session, model, only_active: bool = True) -> dict[int, int]:
    stmt = select(model.company_id, func.count()).group_by(model.company_id)
    if only_active and hasattr(model, "is_active"):
        stmt = stmt.where(model.is_active.is_(True))
    return {cid: n for cid, n in db.execute(stmt).all()}


def list_tenants(db: Session, *, include_suspended: bool = True) -> list[dict]:
    """Every company with the handful of numbers worth seeing at a glance.

    Three grouped counts rather than three subqueries per row: the console
    lists every tenant on one screen, and an N+1 there is an N+1 over the
    whole customer base.
    """
    stmt = select(Company).order_by(Company.id)
    if not include_suspended:
        stmt = stmt.where(Company.is_active.is_(True))
    companies = list(db.execute(stmt).scalars().all())

    users = _count_by_company(db, User)
    products = _count_by_company(db, Product)
    sales = _count_by_company(db, Sale, only_active=False)
    invoicing = _invoicing_states(db)

    return [
        {
            "company": c,
            "user_count": users.get(c.id, 0),
            "product_count": products.get(c.id, 0),
            "sale_count": sales.get(c.id, 0),
            "invoicing": invoicing.get(c.id),
        }
        for c in companies
    ]


def _invoicing_states(db: Session) -> dict[int, str]:
    """Each shop's place in the invoicing setup, for the list's badge.

    ``submitted`` is the one that needs us: the shop finished its steps at
    ARCA and waits for the delegation to be accepted and activated.
    """
    states = {
        company_id: ("submitted" if submitted_at else "draft")
        for company_id, submitted_at in db.execute(
            select(InvoicingRequest.company_id, InvoicingRequest.submitted_at)
        )
    }
    for company_id, is_active in db.execute(select(ArcaIssuer.company_id, ArcaIssuer.is_active)):
        states[company_id] = "active" if is_active else "paused"
    return states


def get_tenant(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise PlatformError("La empresa no existe.")
    return company


def set_tenant_active(
    db: Session, platform_user: PlatformUser, company_id: int, active: bool
) -> Company:
    """Suspend or reactivate a shop. This is the non-payment lever.

    Suspension bites immediately, not at the next login: ``get_current_user``
    re-checks the company on every request.
    """
    company = get_tenant(db, company_id)
    company.is_active = active
    db.add(company)
    record(
        db,
        platform_user,
        PlatformAction.TENANT_REACTIVATE if active else PlatformAction.TENANT_SUSPEND,
        company_id=company.id,
        detail=company.name,
        commit=False,
    )
    db.commit()
    db.refresh(company)
    return company


def tenant_users(db: Session, company_id: int) -> list[User]:
    return list(
        db.execute(
            select(User).where(User.company_id == company_id).order_by(User.id)
        ).scalars().all()
    )


def add_tenant_admin(
    db: Session,
    platform_user: PlatformUser,
    company_id: int,
    *,
    email: str,
    full_name: str,
    password: str | None = None,
) -> tuple[User, bool]:
    """Add another company-level administrator to a tenant.

    Used when a shop owner locks themselves out, or when we onboard a second
    owner. Goes through the same role wiring as provisioning so the new admin
    is identical to the original one.

    Omit ``password`` to email them an invitation instead. Returns
    ``(user, invited)``.
    """
    company = get_tenant(db, company_id)
    email = email.strip().lower()
    clash = db.execute(
        select(User).where(User.company_id == company.id, User.email == email)
    ).scalar_one_or_none()
    if clash:
        raise PlatformError(f"{email} ya es usuario de {company.name}.")

    admin_role, _ = provisioning.ensure_default_roles(db, company.id)
    user = User(
        company_id=company.id,
        email=email,
        full_name=full_name.strip() or "Administrador",
        hashed_password="",
        is_superuser=True,
        roles=[admin_role],
    )
    if password:
        user.hashed_password = hash_password(password)
    else:
        invitations.set_unusable_password(user)
    db.add(user)
    db.flush()
    record(
        db, platform_user, PlatformAction.TENANT_USER_CREATE,
        company_id=company.id, target_user_id=user.id, detail=email, commit=False,
    )
    db.commit()
    db.refresh(user)

    invited = False
    if not password:
        invited = send_invitation(db, platform_user, company, user)
    return user, invited


def reset_tenant_password(
    db: Session,
    platform_user: PlatformUser,
    company_id: int,
    user_id: int,
    new_password: str,
) -> User:
    user = db.execute(
        select(User).where(User.id == user_id, User.company_id == company_id)
    ).scalar_one_or_none()
    if user is None:
        raise PlatformError("El usuario no existe en esa empresa.")
    if not new_password:
        raise PlatformError("La contraseña no puede estar vacía.")
    user.hashed_password = hash_password(new_password)
    db.add(user)
    record(
        db, platform_user, PlatformAction.TENANT_PASSWORD_RESET,
        company_id=company_id, target_user_id=user.id, detail=user.email, commit=False,
    )
    db.commit()
    db.refresh(user)
    return user


def impersonate(
    db: Session,
    platform_user: PlatformUser,
    company_id: int,
    *,
    user_id: int | None = None,
    reason: str | None = None,
) -> tuple[str, User]:
    """Mint a short-lived tenant token so we can see what the shop sees.

    The audit row is committed *before* the token is returned. The token
    carries ``impersonated_by`` so the console can show a banner and nobody
    mistakes a support session for the customer's own.
    """
    company = get_tenant(db, company_id)
    if not company.is_active:
        raise PlatformError(
            "La empresa está suspendida — reactivala antes de ingresar."
        )

    stmt = select(User).where(User.company_id == company_id, User.is_active.is_(True))
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    else:
        # Default to an owner: support questions are almost always about
        # something only an administrator can see.
        stmt = stmt.where(User.is_superuser.is_(True))
    target = db.execute(stmt.order_by(User.id)).scalars().first()
    if target is None:
        raise PlatformError(
            "Esa empresa no tiene un usuario activo al cual ingresar."
        )

    record(
        db, platform_user, PlatformAction.TENANT_IMPERSONATE,
        company_id=company_id, target_user_id=target.id,
        detail=f"as {target.email}" + (f" — {reason}" if reason else ""),
    )
    token = create_access_token(
        target.id,
        extra={
            "company_id": target.company_id,
            "impersonated_by": platform_user.email,
        },
        scope=SCOPE_TENANT,
        expires_minutes=IMPERSONATION_MINUTES,
    )
    return token, target


def create_tenant(
    db: Session, platform_user: PlatformUser, **kwargs
) -> tuple[Company, User, bool]:
    """Provision a tenant and record who did it, as one transaction.

    Returns ``(company, admin, invited)``. When no ``admin_password`` was
    given, an invitation is emailed *after* the transaction commits: the shop
    exists whether or not the mail provider is having a bad day, and a failed
    send is fixed by resending, not by re-onboarding.
    """
    company, admin = provisioning.create_tenant(db, commit=False, **kwargs)
    record(
        db, platform_user, PlatformAction.TENANT_CREATE,
        company_id=company.id, target_user_id=admin.id,
        detail=f"{company.name} — admin {admin.email}", commit=False,
    )
    db.commit()
    db.refresh(company)
    db.refresh(admin)

    invited = False
    if not kwargs.get("admin_password"):
        invited = send_invitation(db, platform_user, company, admin)
    return company, admin, invited


def send_invitation(
    db: Session, platform_user: PlatformUser, company: Company, user: User
) -> bool:
    """Email a set-your-password link and record that we did."""
    ok = invitations.send_invitation(db, user, company)
    record(
        db, platform_user, PlatformAction.TENANT_INVITE_SENT,
        company_id=company.id, target_user_id=user.id,
        detail=f"{user.email}{'' if ok else ' — ENVÍO FALLIDO'}",
    )
    return ok


def resend_invitation(
    db: Session, platform_user: PlatformUser, company_id: int, user_id: int
) -> bool:
    """Send a fresh link, voiding any earlier one for that user."""
    company = get_tenant(db, company_id)
    user = db.execute(
        select(User).where(User.id == user_id, User.company_id == company_id)
    ).scalar_one_or_none()
    if user is None:
        raise PlatformError("El usuario no existe en esa empresa.")
    if not user.is_active:
        raise PlatformError("El usuario está desactivado.")
    return send_invitation(db, platform_user, company, user)


# --- facturación electrónica ------------------------------------------------
# Linking a shop to an arca-api issuer is ours to do, never the shop's: the
# link decides whose CUIT its sales are invoiced under. In delegated mode it
# also needs our own steps at ARCA (accepting the delegation, authorizing the
# certificate), so it belongs on this side anyway.
FISCAL_FIELDS = {
    "commercial_address": "commercialAddress",
    "gross_income_tax": "grossIncomeTax",
    "activity_start_date": "activityStartDate",
    "trade_name": "tradeName",
}


def _issuer_link(db: Session, company_id: int) -> ArcaIssuer | None:
    return db.execute(
        select(ArcaIssuer).where(ArcaIssuer.company_id == company_id)
    ).scalar_one_or_none()


def _arca_error(reply: arca.Reply) -> str:
    if reply.unreachable:
        return reply.unreachable
    body = reply.body or {}
    return body.get("detail") or f"error {reply.status} de arca-api"


def _fiscal_body(data: FiscalData) -> dict:
    body = {}
    for field, key in FISCAL_FIELDS.items():
        value = getattr(data, field)
        if value is not None:
            body[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return body


def _invoicing_request(db: Session, company_id: int) -> InvoicingRequest | None:
    return db.execute(
        select(InvoicingRequest).where(InvoicingRequest.company_id == company_id)
    ).scalar_one_or_none()


def tenant_invoicing(db: Session, company_id: int) -> dict:
    """The shop's link, and what arca-api says about the issuer behind it.

    Before activation it carries what the shop declared in its guide and what
    ARCA's padrón says about that CUIT: the IVA condition can never change
    once the issuer exists, so it is worth comparing with the source first.
    """
    get_tenant(db, company_id)
    link = _issuer_link(db, company_id)
    request = _invoicing_request(db, company_id)
    out: dict = {"linked": link is not None, "configured": arca.configured(), "request": request}
    if link is None:
        if request is not None and request.cuit and arca.configured():
            reply = arca.lookup_taxpayer(request.cuit)
            if reply.ok:
                out["taxpayer"] = reply.body
            elif reply.status == 404:
                out["taxpayer_error"] = ("ARCA no tiene ese CUIT en su padrón. En homologación es "
                                         "normal: el padrón de prueba es sintético.")
            else:
                out["taxpayer_error"] = f"No se pudo consultar el padrón: {_arca_error(reply)}"
        return out
    out.update(
        issuer_id=link.issuer_id, cuit=link.cuit, legal_name=link.legal_name,
        iva_condition=link.iva_condition, point_of_sale=link.point_of_sale,
        is_active=link.is_active,
    )
    reply = arca.get_issuer(link.issuer_id)
    if reply.ok:
        out["issuer"] = reply.body
    else:
        out["error"] = _arca_error(reply)
    return out


def link_tenant_invoicing(
    db: Session, platform_user: PlatformUser, company_id: int, data: TenantInvoicingLink
) -> dict:
    """Turn invoicing on: register the shop's CUIT in arca-api, or link the
    issuer it already has there."""
    company = get_tenant(db, company_id)
    if not arca.configured():
        raise PlatformError(
            "arca-api no está configurado en este servidor (ARCA_API_URL y ARCA_API_KEY)."
        )
    link = _issuer_link(db, company_id)
    if link is not None and db.execute(
        select(Invoice.id).where(Invoice.company_id == company_id).limit(1)
    ).first():
        raise PlatformError(
            "Esta óptica ya emitió comprobantes con su emisor actual: no se puede "
            "cambiar. Para pausarla, desactivá la facturación."
        )

    fiscal = _fiscal_body(data)
    if data.issuer_id:
        reply = arca.get_issuer(data.issuer_id)
        if not reply.ok:
            raise PlatformError(f"arca-api no encontró el emisor {data.issuer_id}: {_arca_error(reply)}")
        issuer = reply.body
    else:
        cuit = data.cuit or "".join(ch for ch in (company.tax_id or "") if ch.isdigit())
        if len(cuit) != 11:
            raise PlatformError("Falta el CUIT de la óptica: 11 dígitos, sin guiones.")
        if data.iva_condition is None:
            raise PlatformError("Indicá la condición frente al IVA de la óptica.")
        reply = arca.create_issuer({
            "cuit": cuit,
            "legalName": data.legal_name or company.legal_name or company.name,
            "ivaCondition": data.iva_condition.value.upper(),
            "credentialMode": "delegated",
            **fiscal,
        })
        fiscal = {}   # sent with the registration
        if reply.status == 201:
            issuer = reply.body
        elif (reply.body or {}).get("code") == "ISSUER_EXISTS":
            # Registered before (an earlier attempt, or by hand): link that one.
            listed = arca.list_issuers()
            matches = [i for i in ((listed.body or {}).get("data") or []) if i.get("cuit") == cuit]
            if not matches:
                raise PlatformError(f"arca-api dice que el CUIT ya existe pero no lo lista: {_arca_error(reply)}")
            issuer = matches[0]
            # The condition can never change in arca-api, and it decides every
            # comprobante's class: linking one registered otherwise would
            # quietly invoice the shop as something it is not.
            registered = issuer["ivaCondition"].lower()
            if registered != data.iva_condition.value:
                raise PlatformError(
                    f"arca-api ya tiene el CUIT {cuit} registrado como {registered.replace('_', ' ')}, "
                    f"no como {data.iva_condition.value.replace('_', ' ')}. Revisá la condición; si la "
                    f"registrada es la correcta, vinculá ese emisor por su id ({issuer['id']})."
                )
        else:
            raise PlatformError(f"arca-api no registró el emisor: {_arca_error(reply)}")

    clash = db.execute(
        select(ArcaIssuer.company_id).where(
            ArcaIssuer.issuer_id == issuer["id"], ArcaIssuer.company_id != company_id
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise PlatformError(f"El emisor {issuer['id']} ya está vinculado a la empresa #{clash}.")
    if fiscal:
        reply = arca.update_issuer(issuer["id"], fiscal)
        if not reply.ok:
            raise PlatformError(f"arca-api no guardó los datos fiscales: {_arca_error(reply)}")

    link = link or ArcaIssuer(company_id=company_id)
    link.issuer_id = issuer["id"]
    link.cuit = issuer["cuit"]
    link.legal_name = issuer["legalName"]
    link.iva_condition = issuer["ivaCondition"].lower()
    link.point_of_sale = data.point_of_sale
    link.is_active = True
    db.add(link)
    record(
        db, platform_user, PlatformAction.TENANT_INVOICING_LINK, company_id=company_id,
        detail=f"{link.issuer_id} CUIT {link.cuit} {link.iva_condition} PdV {link.point_of_sale}",
        commit=False,
    )
    request = _invoicing_request(db, company_id)
    if request is not None:
        request.provider_note = None   # answered: it is active now
    db.commit()
    if request is not None:
        _mail_submitter(db, company, request, lambda user: email_templates.invoicing_active(
            full_name=user.full_name, company_name=company.name, link=_guide_link()))
    return tenant_invoicing(db, company_id)


def update_tenant_invoicing(
    db: Session, platform_user: PlatformUser, company_id: int, data: TenantInvoicingUpdate
) -> dict:
    """Punto de venta, pausing invoicing, and the issuer's fiscal data."""
    get_tenant(db, company_id)
    link = _issuer_link(db, company_id)
    if link is None:
        raise PlatformError("Esta óptica no tiene la facturación vinculada.")
    changed = []
    if data.point_of_sale is not None and data.point_of_sale != link.point_of_sale:
        link.point_of_sale = data.point_of_sale
        changed.append(f"punto de venta {data.point_of_sale}")
    if data.is_active is not None and data.is_active != link.is_active:
        link.is_active = data.is_active
        changed.append("activada" if data.is_active else "pausada")
    fiscal = _fiscal_body(data)
    if fiscal:
        reply = arca.update_issuer(link.issuer_id, fiscal)
        if not reply.ok:
            raise PlatformError(f"arca-api no guardó los datos fiscales: {_arca_error(reply)}")
        changed.extend(sorted(fiscal))
    if changed:
        record(
            db, platform_user, PlatformAction.TENANT_INVOICING_UPDATE,
            company_id=company_id, detail=", ".join(changed), commit=False,
        )
    db.commit()
    return tenant_invoicing(db, company_id)


def tenant_invoicing_health(db: Session, company_id: int) -> dict:
    """arca-api's own check: ARCA up, the ticket valid, the CUIT represented."""
    get_tenant(db, company_id)
    link = _issuer_link(db, company_id)
    if link is None:
        raise PlatformError("Esta óptica no tiene la facturación vinculada.")
    reply = arca.issuer_health(link.issuer_id)
    if not reply.ok:
        raise PlatformError(f"arca-api no respondió el chequeo: {_arca_error(reply)}")
    return reply.body


def set_invoicing_note(
    db: Session, platform_user: PlatformUser, company_id: int, note: str | None
) -> dict:
    """Answer a shop's request from here ("todavía no vemos la delegación").

    The note shows in its guide and is mailed to whoever sent it. An empty
    note clears it.
    """
    company = get_tenant(db, company_id)
    request = _invoicing_request(db, company_id)
    if request is None:
        raise PlatformError("Esta óptica todavía no empezó la guía de facturación.")
    note = (note or "").strip() or None
    request.provider_note = note
    record(
        db, platform_user, PlatformAction.TENANT_INVOICING_NOTE, company_id=company_id,
        detail=note or "nota borrada", commit=False,
    )
    db.commit()
    if note:
        _mail_submitter(db, company, request, lambda user: email_templates.invoicing_note(
            full_name=user.full_name, company_name=company.name, note=note, link=_guide_link()))
    return tenant_invoicing(db, company_id)


def notify_invoicing_request(db: Session, company_id: int) -> int:
    """Tell every provider operator that a shop is waiting for activation.

    Returns how many messages went out. Never raises: the shop's request is
    saved either way, and /admin lists it whether or not the mail arrived.
    """
    company = get_tenant(db, company_id)
    request = _invoicing_request(db, company_id)
    if request is None or request.submitted_at is None:
        return 0
    condition = (request.iva_condition or "").replace("_", " ")
    message = email_templates.invoicing_request(
        company_name=company.name, cuit=request.cuit or "", condition=condition,
        point_of_sale=request.point_of_sale or 0,
        link=f"{settings.public_base_url.rstrip('/')}/admin",
    )
    sent = 0
    for operator in db.execute(
        select(PlatformUser).where(PlatformUser.is_active.is_(True))
    ).scalars():
        sent += email.send(replace(message, to=operator.email))
    return sent


def _guide_link() -> str:
    return f"{settings.public_base_url.rstrip('/')}/app#/company"


def _mail_submitter(db: Session, company: Company, request: InvoicingRequest, build) -> bool:
    """Mail whoever sent the guide, if they still can receive it."""
    if request.submitted_by_user_id is None:
        return False
    user = db.get(User, request.submitted_by_user_id)
    if user is None or not user.is_active or user.company_id != company.id:
        return False
    return email.send(replace(build(user), to=user.email))
