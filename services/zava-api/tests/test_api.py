from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["counts"]["products"] == 576
    assert body["counts"]["facilities"] == 7


def test_hero_product():
    response = client.get("/products/ZCPTM-SS-S-B0")
    assert response.status_code == 200
    body = response.json()
    assert body["sku"] == "ZCPTM-SS-S-B0"
    assert body["product_line"] == "ZavaCore Field Premium"


def test_critical_product_stock():
    response = client.get("/products/ZCPTM-LS-L-RR/stock")
    assert response.status_code == 200
    body = response.json()
    clt = next(item for item in body["facilities"] if item["facility_code"] == "FC-CLT")
    assert clt["status"] == "critical"
    assert clt["on_hand"] == 15
    assert clt["reorder_point"] == 80


def test_critical_alerts_include_hero():
    response = client.get("/inventory/alerts?severity=critical")
    assert response.status_code == 200
    alerts = response.json()
    hero = next(item for item in alerts if item["sku"] == "ZCPTM-LS-L-RR" and item["facility_code"] == "FC-CLT")
    assert hero["on_hand"] == 15
    assert hero["reorder_point"] == 80
    assert hero["projected_stockout_days"] == 3


def test_inventory_summary_kpis():
    response = client.get("/inventory/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_skus"] == 576
    assert body["facilities"] == 7
    assert body["retail_stores"] == 3
    assert body["product_lines"] == 4


def test_order_23518_tracking_card():
    response = client.get("/orders/23518")
    assert response.status_code == 200
    body = response.json()
    assert body["status_label"] == "Delayed - Weather"
    assert body["carrier"] == "Zava Express"
    assert body["tracking_number"] == "ZVX-7489201374829"
    assert body["recipient_name"] == "Jane Smith"
    assert body["items"]


def test_order_23590_delivered():
    response = client.get("/orders/23590")
    assert response.status_code == 200
    assert response.json()["status_label"] == "Delivered"


def test_bogus_order_404():
    response = client.get("/orders/99999")
    assert response.status_code == 404
