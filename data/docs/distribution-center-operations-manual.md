# Distribution Center Operations Manual
This manual maps ZavaCore Field fulfillment work to order statuses and standardizes operations across the seven-DC network.

## Network scope
Zava fulfills online and retail-replenishment demand from `FC-MEM` Zava Memphis Distribution Center, `FC-CLT` Zava Charlotte Distribution Center, `FC-SEA` Zava Seattle Distribution Center, `FC-DFW` Zava Dallas Distribution Center, `FC-EWR` Zava Newark Distribution Center, `FC-RNO` Zava Reno Distribution Center, and `FC-CMH` Zava Columbus Distribution Center. Each DC stores Core, Pro, Premium, and Elite apparel across Tops/Tees, Shorts, and Pants.

Network routing assigns orders based on inventory availability, customer destination, carrier service, and workload. Retail transfers to `ST-AUS`, `ST-MIA`, and `ST-CHI` may be consolidated when store service levels allow.

## Pick, pack, and ship flow
The customer status `processing` covers order release, inventory reservation, picking, packing, and carrier staging. Once a carrier accepts the shipment and scans movement, the order becomes `in_transit`. A final-mile scan moves it to `out_for_delivery`, and proof of delivery or carrier confirmation moves it to `delivered`.

If an order cannot progress normally, the operations team assigns `delayed` for Weather, Customs, or Volume reasons, or `exception` for Address or Damaged reasons. A pick short should not be hidden as a carrier delay. It must be resolved through inventory recount, substitute DC sourcing, split shipment, or customer-care escalation.

## Bin-location scheme
Zava bin locations use a facility-zone-aisle-bay-level-position format. Example: `CLT-B-14-06-C-02` identifies Charlotte, zone B, aisle 14, bay 06, level C, position 02. Pick faces are separated by garment and size family where possible to reduce mispicks. Premium and Elite fast movers may be placed in forward-pick zones during launches or seasonal campaigns.

Every pick requires SKU scan validation. SKU codes follow `ZC{Line}{Garment}{Gender}-{Cut}-{Size}-{Color}`, so team members must verify line, garment, gender, cut, size, and colorway before closing a pick. Similar colorways such as Black/Orange and Teal/Orange must not be substituted without customer approval.

## Cutoff times and carrier staging
Standard parcel same-day processing cutoffs are 2:00 p.m. local DC time for Zava Express, 3:00 p.m. local DC time for Swift Post, and 11:00 a.m. local DC time for Metro Freight consolidations. Late orders remain in `processing` until the next shipping wave unless customer care authorizes expedited handling.

Carrier staging lanes must be physically separated and clearly labeled. International shipments require document verification before staging. Orders with unresolved address warnings must remain on hold and must not be released to carrier.

## Quality and safety checks
Packers verify SKU, size, colorway, item count, return insert, and shipping label. Apparel must be folded or bagged to protect fabric, tags, and presentation. Damaged, stained, or tag-missing units are moved to hold for disposition and cannot be shipped as first-quality product. A clean pack standard protects customer experience and reduces returns.

---
**Document metadata**
- doc_id: ZAVA-DCOPS-01
- category: manual
- audience: ops
- last_updated: 2026-01-31
- owner: Zava Distribution Operations
