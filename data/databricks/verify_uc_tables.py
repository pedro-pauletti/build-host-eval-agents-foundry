"""Cross-check the Unity Catalog load against the numbers the Fabric side reports."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _dbx import fq, sql  # noqa: E402

CHECKS = [
    ("total on-hand, Premium line", f"""
        SELECT sum(i.on_hand) FROM {fq('inventory')} i
        JOIN {fq('products')} p ON p.sku = i.sku WHERE p.line_code = 'P'""", "203857"),
    ("total on-hand, Elite line", f"""
        SELECT sum(i.on_hand) FROM {fq('inventory')} i
        JOIN {fq('products')} p ON p.sku = i.sku WHERE p.line_code = 'E'""", "198596"),
    ("ZCPTM-SS-S-B0 across facilities",
     f"SELECT sum(on_hand) FROM {fq('inventory')} WHERE sku = 'ZCPTM-SS-S-B0'", "1672"),
    ("critical SKUs at FC-CLT",
     f"SELECT count(*) FROM {fq('inventory')} WHERE facility_code = 'FC-CLT' AND status = 'critical'", "49"),
    ("stock status split",
     f"SELECT concat_ws('/', count_if(status='in stock'), count_if(status='low stock'), count_if(status='critical')) "
     f"FROM {fq('inventory')}", "3141/536/355"),
    ("order 23518 status",
     f"SELECT concat_ws(' | ', status_label, cast(estimated_delivery as string), tracking_number) "
     f"FROM {fq('orders')} WHERE order_id = '23518'", "Delayed - Weather | 2026-02-17 | ZVX-7489201374829"),
]

print(f"{'check':38s} {'esperado':44s} obtido")
ok = True
for label, statement, expected in CHECKS:
    got = str((sql(statement)["result"]["data_array"] or [[None]])[0][0])
    mark = "OK " if got == expected else "XX "
    ok &= got == expected
    print(f"{mark}{label:36s} {expected:44s} {got}")

print("\nreceita por linha de produto:")
rows = sql(f"""
    SELECT p.product_line, round(sum(s.revenue), 2) AS revenue
    FROM {fq('sales')} s JOIN {fq('products')} p ON p.sku = s.sku
    GROUP BY p.product_line ORDER BY revenue DESC
""")["result"]["data_array"]
for line, rev in rows:
    print(f"   {line:28s} {rev}")

sys.exit(0 if ok else 1)
