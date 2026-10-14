"""Payment reminders by WhatsApp: the wording, the number, and the record."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.company import Company
from app.models.enums import ReminderTone
from app.models.sales import Sale
from app.services import clock
from app.services import payment_reminders as reminders
from tests.test_sales import make_sale, shop  # noqa: F401 (fixtures)

# Noon in Buenos Aires on Tuesday 13 October 2026.
NOON = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 13)


# --- wording ---------------------------------------------------------------

@pytest.mark.parametrize("due, phrase", [
    (None, "sigue pendiente"),
    (date(2026, 10, 13), "vence hoy"),
    (date(2026, 10, 14), "vence mañana"),
    (date(2026, 10, 16), "vence el viernes 16/10"),
    (date(2026, 10, 23), "vence el 23/10"),           # beyond a week, no weekday
    (date(2027, 1, 5), "vence el 05/01/2027"),
    (date(2026, 10, 12), "venció ayer"),
    (date(2026, 10, 10), "venció el sábado 10/10"),
    (date(2026, 9, 30), "venció el 30/09"),
])
def test_due_phrase(due, phrase):
    assert reminders.due_phrase(due, TODAY) == phrase


@pytest.mark.parametrize("sold, phrase", [
    (date(2026, 10, 13), "de hoy"),
    (date(2026, 10, 12), "de ayer"),
    (date(2026, 9, 1), "del 01/09"),
    (date(2025, 12, 20), "del 20/12/2025"),
])
def test_bought_phrase(sold, phrase):
    assert reminders.bought_phrase(sold, TODAY) == phrase


@pytest.mark.parametrize("value, currency, text", [
    ("45000", "ARS", "$45.000"),
    ("45000.50", "ARS", "$45.000,50"),
    ("1234567.89", "ARS", "$1.234.567,89"),
    ("999", None, "$999"),
    ("1200", "USD", "US$1.200"),
])
def test_money_text(value, currency, text):
    assert reminders.money_text(Decimal(value), currency) == text


@pytest.mark.parametrize("hour, said", [
    (5, "Buen día"), (11, "Buen día"), (12, "Buenas tardes"),
    (19, "Buenas tardes"), (20, "Buenas noches"), (2, "Buenas noches"),
])
def test_greeting(hour, said):
    assert reminders.greeting(hour) == said


@pytest.mark.parametrize("days_left, tone", [
    (None, ReminderTone.FRIENDLY),
    (5, ReminderTone.FRIENDLY),
    (0, ReminderTone.FRIENDLY),
    (-1, ReminderTone.FORMAL),
    (-reminders.FIRM_AFTER_DAYS, ReminderTone.FORMAL),
    (-reminders.FIRM_AFTER_DAYS - 1, ReminderTone.FIRM),
])
def test_suggest(days_left, tone):
    assert reminders.suggest(days_left) is tone


def _facts(**overrides):
    base = dict(first_name="Juan", full_name="Juan Pérez", shop="Óptica Visión",
                balance="$45.000", bought="del 01/10", due="vence el viernes 16/10",
                upcoming=True, greeting="Buenas tardes")
    return reminders.Facts(**{**base, **overrides})


@pytest.mark.parametrize("facts", [
    _facts(),
    _facts(upcoming=False, due="venció el sábado 10/10"),
    _facts(upcoming=False, due="sigue pendiente"),
    _facts(first_name="", full_name=""),
])
def test_every_message_is_fit_to_send(facts):
    """No em dash (CLAUDE.md), nothing that assumes a gender, and the facts
    the customer needs: who writes, how much, and when."""
    texts = reminders.messages(facts)
    assert set(texts) == set(ReminderTone)
    for tone, text in texts.items():
        assert "\u2014" not in text                    # em dash
        assert "stimad" not in text                     # Estimado/a
        for fact in (facts.shop, facts.balance, facts.bought, facts.due):
            assert fact in text, (tone, fact)
    # Formal is de usted; the other two are de vos.
    assert "su compra" in texts[ReminderTone.FORMAL] and "tu compra" not in texts[ReminderTone.FORMAL]
    assert "tu compra" in texts[ReminderTone.FRIENDLY]
    assert "tu compra" in texts[ReminderTone.FIRM]


def test_a_message_without_a_name_still_greets():
    texts = reminders.messages(_facts(first_name="", full_name=""))
    assert texts[ReminderTone.FRIENDLY].startswith("¡Hola! ")
    assert texts[ReminderTone.FORMAL].startswith("Buenas tardes. ")
    assert texts[ReminderTone.FIRM].startswith("Hola. ")


def test_overdue_wording_asks_to_regularise():
    texts = reminders.messages(_facts(upcoming=False, due="venció el sábado 10/10"))
    assert "regularices a la brevedad" in texts[ReminderTone.FIRM]
    assert texts[ReminderTone.FIRM].startswith("Hola, Juan. El saldo de $45.000")
    assert "regularizarlo a la brevedad" in texts[ReminderTone.FORMAL]
    assert "avisanos cómo te queda más cómodo" in texts[ReminderTone.FRIENDLY]


# --- the endpoints ---------------------------------------------------------

@pytest.fixture
def debtor(client, auth_headers, db, monkeypatch):
    """A customer who owes $45.000, with a mobile written the old way, at
    "Óptica Visión", seen at noon on Tuesday 13/10."""
    monkeypatch.setattr(clock, "_now", lambda: NOON)
    company = db.get(Company, 1)
    company.name = "Óptica Visión"
    db.commit()
    return client.post(
        "/api/customers",
        json={"first_name": "JUAN", "last_name": "PÉREZ", "phone": "011 15 5555-0000"},
        headers=auth_headers,
    ).json()


def owing_sale(client, headers, shop, db, customer, promised="2026-10-16", **kw):
    sale = make_sale(
        client, headers, shop, customer_id=customer["id"],
        payments=[{"amount": "5000", "method": "cash"}],
        promised_payment_date=promised, **kw,
    )
    assert sale.status_code == 201, sale.text
    sale = sale.json()
    db.get(Sale, sale["id"]).sold_at = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
    db.commit()
    return sale


def test_draft_words_the_debt_in_three_tones(client, auth_headers, shop, db, debtor):
    sale = owing_sale(client, auth_headers, shop, db, debtor)
    resp = client.get(f"/api/sales/{sale['id']}/whatsapp", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    draft = resp.json()

    assert (draft["sale_number"], draft["balance"]) == (sale["number"], "45000.00")
    assert draft["promised_payment_date"] == "2026-10-16"
    assert draft["customer_name"] == "Juan Pérez"
    assert draft["phone"] == "011 15 5555-0000"             # as registered
    assert draft["whatsapp_number"] == "5491155550000"
    assert draft["whatsapp_display"] == "+54 9 11 5555-0000"
    assert draft["phone_problem"] is None
    assert draft["suggested_tone"] == "friendly"
    assert draft["reminders"] == []
    texts = {m["tone"]: m["text"] for m in draft["messages"]}
    assert list(texts) == ["friendly", "formal", "firm"]
    assert texts["friendly"] == (
        "¡Hola, Juan! Te escribimos de Óptica Visión para recordarte que el saldo "
        "de $45.000 de tu compra del 01/10 vence el viernes 16/10. Si necesitás "
        "algo, escribinos por acá. ¡Gracias!"
    )
    assert texts["formal"].startswith("Buenas tardes, Juan Pérez. Le escribimos de Óptica Visión")
    assert texts["firm"] == (
        "Hola, Juan. Te recordamos que el saldo de $45.000 de tu compra del 01/10 "
        "en Óptica Visión vence el viernes 16/10. Es importante que lo abones en "
        "la fecha acordada. Gracias."
    )


@pytest.mark.parametrize("promised, phrase, tone", [
    ("2026-10-13", "vence hoy", "friendly"),
    ("2026-10-10", "venció el sábado 10/10", "formal"),
    ("2026-10-01", "venció el 01/10", "firm"),
    (None, "sigue pendiente", "friendly"),
])
def test_the_date_decides_the_wording_and_the_suggestion(
    client, auth_headers, shop, db, debtor, promised, phrase, tone
):
    sale = owing_sale(client, auth_headers, shop, db, debtor, promised=promised)
    draft = client.get(f"/api/sales/{sale['id']}/whatsapp", headers=auth_headers).json()
    assert draft["suggested_tone"] == tone
    assert all(phrase in m["text"] for m in draft["messages"])


def test_a_phone_that_cannot_be_read_says_why(client, auth_headers, shop, db, debtor):
    client.put(f"/api/customers/{debtor['id']}", json={"phone": "4555-0000"},
               headers=auth_headers)
    sale = owing_sale(client, auth_headers, shop, db, debtor)
    draft = client.get(f"/api/sales/{sale['id']}/whatsapp", headers=auth_headers).json()
    assert draft["whatsapp_number"] is None
    assert "código de área" in draft["phone_problem"]
    assert len(draft["messages"]) == 3                    # still worded, to send once fixed

    sent = client.post(f"/api/sales/{sale['id']}/whatsapp",
                       json={"tone": "friendly", "message": "Hola"}, headers=auth_headers)
    assert sent.status_code == 400
    assert "código de área" in sent.json()["detail"]

    client.put(f"/api/customers/{debtor['id']}", json={"phone": "11 4444-0000"},
               headers=auth_headers)
    draft = client.get(f"/api/sales/{sale['id']}/whatsapp", headers=auth_headers).json()
    assert draft["whatsapp_number"] == "5491144440000"


def test_sending_is_recorded_against_the_registered_phone(
    client, auth_headers, shop, db, debtor
):
    sale = owing_sale(client, auth_headers, shop, db, debtor)
    sent = client.post(
        f"/api/sales/{sale['id']}/whatsapp",
        # A number sent along is ignored: the reminder goes to the file's.
        json={"tone": "firm", "message": "  Hola, Juan.  ", "phone": "5493515123456"},
        headers=auth_headers,
    )
    assert sent.status_code == 201, sent.text
    reminder = sent.json()
    assert reminder["tone"] == "firm"
    assert reminder["phone"] == "5491155550000"
    assert reminder["sent_by_name"] == "Admin"

    detail = client.get(f"/api/sales/{sale['id']}", headers=auth_headers).json()
    assert [r["id"] for r in detail["payment_reminders"]] == [reminder["id"]]
    draft = client.get(f"/api/sales/{sale['id']}/whatsapp", headers=auth_headers).json()
    assert [r["id"] for r in draft["reminders"]] == [reminder["id"]]

    stored = db.get(Sale, sale["id"]).payment_reminders[0]
    assert stored.message == "Hola, Juan."                  # trimmed, as sent


def test_the_lists_show_the_latest_reminder(client, auth_headers, shop, db, debtor):
    sale = owing_sale(client, auth_headers, shop, db, debtor)
    other = owing_sale(client, auth_headers, shop, db, debtor)
    for tone in ("friendly", "formal"):
        assert client.post(f"/api/sales/{sale['id']}/whatsapp",
                           json={"tone": tone, "message": "Hola"},
                           headers=auth_headers).status_code == 201
    rows = {r["id"]: r for r in
            client.get("/api/sales?pending_only=true", headers=auth_headers).json()}
    assert rows[sale["id"]]["last_payment_reminder"]["tone"] == "formal"
    assert rows[other["id"]]["last_payment_reminder"] is None


def test_only_a_debt_gets_a_reminder(client, auth_headers, shop, db, debtor):
    paid = make_sale(client, auth_headers, shop, customer_id=debtor["id"],
                     payments=[{"amount": "50000", "method": "cash"}]).json()
    quote = make_sale(client, auth_headers, shop, customer_id=debtor["id"],
                      status="quote").json()
    cancelled = owing_sale(client, auth_headers, shop, db, debtor)
    client.post(f"/api/sales/{cancelled['id']}/cancel", headers=auth_headers)
    for sale in (paid, quote, cancelled):
        for resp in (
            client.get(f"/api/sales/{sale['id']}/whatsapp", headers=auth_headers),
            client.post(f"/api/sales/{sale['id']}/whatsapp",
                        json={"tone": "friendly", "message": "Hola"}, headers=auth_headers),
        ):
            assert resp.status_code == 400
            assert resp.json()["detail"] == "La venta no tiene saldo pendiente."


def test_a_blank_message_is_refused(client, auth_headers, shop, db, debtor):
    sale = owing_sale(client, auth_headers, shop, db, debtor)
    resp = client.post(f"/api/sales/{sale['id']}/whatsapp",
                       json={"tone": "friendly", "message": "   "}, headers=auth_headers)
    assert resp.status_code == 422


def test_sending_needs_sales_write(client, auth_headers, shop, db, debtor):
    sale = owing_sale(client, auth_headers, shop, db, debtor)
    perms = client.get("/api/permissions", headers=auth_headers).json()
    role = client.post("/api/roles", json={
        "name": "Consulta",
        "permission_ids": [p["id"] for p in perms if p["code"] in ("sales:read", "customers:read")],
    }, headers=auth_headers).json()
    client.post("/api/users", json={
        "email": "consulta@test.com", "full_name": "Consulta",
        "password": "consulta1234", "role_ids": [role["id"]],
    }, headers=auth_headers)
    token = client.post("/api/auth/login", json={
        "email": "consulta@test.com", "password": "consulta1234"}).json()["access_token"]
    reader = {"Authorization": f"Bearer {token}"}

    assert client.get(f"/api/sales/{sale['id']}", headers=reader).status_code == 200
    assert client.get(f"/api/sales/{sale['id']}/whatsapp", headers=reader).status_code == 403
    assert client.post(f"/api/sales/{sale['id']}/whatsapp",
                       json={"tone": "friendly", "message": "Hola"},
                       headers=reader).status_code == 403


def test_another_shop_cannot_reach_the_sale(
    client, auth_headers, platform_headers, shop, db, debtor
):
    sale = owing_sale(client, auth_headers, shop, db, debtor)
    resp = client.post("/api/admin/tenants", json={
        "name": "Óptica B", "admin_email": "b@test.com", "admin_full_name": "B",
        "admin_password": "opticab12345",
    }, headers=platform_headers)
    assert resp.status_code == 201, resp.text
    token = client.post("/api/auth/login", json={
        "email": "b@test.com", "password": "opticab12345"}).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}

    assert client.get(f"/api/sales/{sale['id']}/whatsapp", headers=other).status_code == 404
    assert client.post(f"/api/sales/{sale['id']}/whatsapp",
                       json={"tone": "friendly", "message": "Hola"},
                       headers=other).status_code == 404
