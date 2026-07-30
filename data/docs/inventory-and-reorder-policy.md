# Inventory and Reorder Policy
This policy defines how ZavaCore Field apparel inventory is classified, replenished, counted, and escalated across Zava's distribution network.

## Scope and inventory measures
Zava tracks inventory per SKU per distribution center for the ZavaCore Field collection. Each record includes `on_hand`, `reserved`, `available`, `reorder_point`, `safety_stock`, `projected_stockout_days`, and a derived status. The policy applies to all product lines: Core, Pro, Premium, and Elite; all garments: Tops/Tees, Shorts, and Pants; all sizes: S, M, L, and XL; and all colorways: Black/Orange, Charcoal/Silver, Deep Red/Red, and Teal/Orange.

Inventory is managed across seven distribution centers: `FC-MEM` Zava Memphis Distribution Center, `FC-CLT` Zava Charlotte Distribution Center, `FC-SEA` Zava Seattle Distribution Center, `FC-DFW` Zava Dallas Distribution Center, `FC-EWR` Zava Newark Distribution Center, `FC-RNO` Zava Reno Distribution Center, and `FC-CMH` Zava Columbus Distribution Center. Retail replenishment for `ST-AUS`, `ST-MIA`, and `ST-CHI` is planned from the closest available DC unless service levels require a cross-network transfer.

## Reorder points and safety stock
Reorder points are calculated from forecast demand during replenishment lead time plus safety stock. Forecasts must consider product line, garment type, size curve, colorway, online demand, store demand, promotions, and regional seasonality. Safety stock is higher for launch items, high-velocity sizes, and lines with strong event demand.

Premium and Elite items may carry higher service-level targets than Core basics because stock-outs can affect customer loyalty and campaign performance. The planted critical alert at `FC-CLT` for `ZCPTM-LS-L-RR` illustrates this logic: 15 units on hand against a reorder point of 80 and a projected stock-out in 3 days is critical.

## Status thresholds and projected stock-out
Inventory status must be assigned consistently. A SKU-facility record is **critical** when `on_hand < 0.2 × reorder_point` or `projected_stockout_days ≤ 3`. It is **low stock** when `on_hand < reorder_point` but does not meet the critical rule. It is **in stock** when on-hand quantity is at or above reorder point and projected stock-out is greater than 3 days.

Projected stock-out days are calculated by comparing available inventory to the near-term demand forecast. When recent demand is abnormal, planners may override the forecast only with a note explaining the promotion, weather event, store opening, or data-quality issue.

## Cycle counts and accuracy
Cycle counts are scheduled by velocity and risk. Critical and low-stock SKUs are counted within 1 business day when a replenishment decision depends on accuracy. High-velocity Premium and Elite SKUs are counted weekly, other active SKUs monthly, and slow movers quarterly. Variances must be coded as receiving error, pick short, return disposition, transfer mismatch, damage, or count correction.

## Replenishment and purchase-order approval
The replenishment planner reviews critical alerts daily and low-stock items at least three times weekly. Replenishment options include supplier purchase order, inter-DC transfer, retail-store rebalancing, or allocation hold. Purchase orders under $25,000 may be approved by Inventory Operations. Orders from $25,000 to $100,000 require Supply Chain Director approval. Orders above $100,000, expedited freight, or allocation overrides require Finance review.

---
**Document metadata**
- doc_id: ZAVA-INVENTORY-01
- category: policy
- audience: ops
- last_updated: 2026-01-31
- owner: Zava Supply Chain
