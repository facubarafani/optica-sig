from decimal import Decimal


def _inbound(client, headers, product_id, branch_id, qty):
    return client.post(
        "/api/stock/movements",
        json={
            "product_id": product_id, "branch_id": branch_id,
            "movement_type": "inbound", "quantity": str(qty),
        },
        headers=headers,
    )


def test_inbound_creates_level(client, auth_headers, product_id, branch_id):
    resp = _inbound(client, auth_headers, product_id, branch_id, 10)
    assert resp.status_code == 201, resp.text
    assert resp.json()["resulting_quantity"] == "10.00"

    levels = client.get(
        f"/api/stock/levels?product_id={product_id}", headers=auth_headers
    ).json()
    assert len(levels) == 1
    assert levels[0]["quantity"] == "10.00"


def test_outbound_reduces_and_blocks_negative(client, auth_headers, product_id, branch_id):
    _inbound(client, auth_headers, product_id, branch_id, 5)

    ok = client.post(
        "/api/stock/movements",
        json={"product_id": product_id, "branch_id": branch_id,
              "movement_type": "outbound", "quantity": "3"},
        headers=auth_headers,
    )
    assert ok.status_code == 201
    assert ok.json()["resulting_quantity"] == "2.00"

    # Now only 2 left; selling 5 must fail (negative stock disallowed by default).
    bad = client.post(
        "/api/stock/movements",
        json={"product_id": product_id, "branch_id": branch_id,
              "movement_type": "outbound", "quantity": "5"},
        headers=auth_headers,
    )
    assert bad.status_code == 400
    assert "Insufficient stock" in bad.json()["detail"]


def test_transfer_between_branches(client, auth_headers, product_id, branch_id):
    # second branch
    second = client.post(
        "/api/branches", json={"name": "Norte", "code": "NORTE"}, headers=auth_headers
    ).json()["id"]
    _inbound(client, auth_headers, product_id, branch_id, 10)

    resp = client.post(
        "/api/stock/transfers",
        json={"product_id": product_id, "from_branch_id": branch_id,
              "to_branch_id": second, "quantity": "4"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    legs = resp.json()
    assert len(legs) == 2

    levels = {
        lv["branch_id"]: lv["quantity"]
        for lv in client.get(
            f"/api/stock/levels?product_id={product_id}", headers=auth_headers
        ).json()
    }
    assert levels[branch_id] == "6.00"
    assert levels[second] == "4.00"


def test_movement_ledger_records_each_change(client, auth_headers, product_id, branch_id):
    _inbound(client, auth_headers, product_id, branch_id, 10)
    _inbound(client, auth_headers, product_id, branch_id, 5)
    movements = client.get(
        f"/api/stock/movements?product_id={product_id}", headers=auth_headers
    ).json()
    assert len(movements) == 2


def test_stock_service_unit(db, product_id, branch_id):
    """Direct service test: apply_movement keeps level + ledger in sync."""
    from app.schemas.stock import StockMovementCreate
    from app.services import stock as stock_service

    mv = stock_service.apply_movement(
        db,
        StockMovementCreate(
            product_id=product_id, branch_id=branch_id,
            movement_type="inbound", quantity=Decimal("7"),
        ),
        company_id=1,
    )
    assert mv.resulting_quantity == Decimal("7")
    level = stock_service.get_level(
        db, company_id=1, product_id=product_id, branch_id=branch_id
    )
    assert level.quantity == Decimal("7")
