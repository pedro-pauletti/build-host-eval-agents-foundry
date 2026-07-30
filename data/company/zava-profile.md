# Zava — Company Profile & Demo Canon

> **Fictitious company.** Everything here is invented for the demo. This file is the **single source of
> truth**: the Zava REST APIs, the Fabric datasets, the knowledge-base documents, and the notebooks all
> derive their entities (products, facilities, orders…) from the canonical data generated alongside this
> profile (`data/structured/`). The data model and agent inputs/outputs mirror the reference UI in
> `docs/ux-reference/` (`zava-inventory-agent.png`, `zava-delivery-agent.png`).

## 1. Who is Zava?

**Zava** is a **direct-to-consumer (B2C) athletic apparel brand** — performance tops, tees, shorts, and
pants sold under the **ZavaCore Field** collection. Zava sells online and through a few flagship retail
stores, and fulfills orders from **7 regional distribution centers**. It is data-driven and fast-growing.

- Founded: 2018 · HQ: Austin, TX
- Collection: **ZavaCore Field** — 4 product lines (tiers): **Core, Pro, Premium, Elite**
- **576 SKUs**, **7 distribution facilities**, **3 flagship retail stores**
- Channel: **B2C**
- Tagline: *"Built for the field."*

## 2. Business problems this demo addresses

1. **Inventory operations** need fast, natural-language answers about stock levels, reorder points,
   critical/low-stock alerts, projected stock-outs, and policies — across facilities and product lines.
2. **Customers** need reliable **order tracking** and delivery support (delays, exceptions) without
   waiting for a human agent.

## 3. Product model (source of truth for 576 SKUs)

The catalog is the full cross-product of these dimensions (**4 × 3 × 3 × 4 × 4 = 576**):

| Dimension | Values |
|-----------|--------|
| **Product line (tier)** | `Core` (C), `Pro` (R), `Premium` (P), `Elite` (E) |
| **Garment** | `Top`/`Tee` (T), `Shorts` (S), `Pants` (P) |
| **Gender** | `Mens` (M), `Womens` (W), `Youth` (Y) |
| **Size** | `Small` (S), `Medium` (M), `Large` (L), `XL` (XL) |
| **Colorway** | Black/Orange (B0), Charcoal/Silver (CS), Deep Red/Red (RR), Teal/Orange (T0) |

- **Product line names:** `ZavaCore Field Core`, `ZavaCore Field Pro`, `ZavaCore Field Premium`,
  `ZavaCore Field Elite`. All are channel **B2C**.
- **Tops** carry a sleeve style: **SS** (short sleeve) for the B0/CS colorways, **LS** (long sleeve) for
  RR/T0. The **Elite** line labels its tops as **"Tee"**; other lines label them **"Top"**.
- **Shorts** use cut code `AS`, **Pants** use cut code `AP`.

### SKU convention
`ZC{Line}{Garment}{Gender}-{Cut}-{Size}-{Color}`

| Example SKU | Decodes to |
|-------------|-----------|
| `ZCPTM-SS-S-B0` | Premium · Top · Mens · Short-Sleeve · Small · Black/Orange → *"Premium Mens SS Top Small Black/Orange"* |
| `ZCPTM-LS-L-RR` | Premium · Top · Mens · Long-Sleeve · Large · Deep Red/Red → *"Premium Mens LS Top Large Deep Red/Red"* |
| `ZCETM-SS-M-B0` | Elite · Tee · Mens · Short-Sleeve · Medium · Black/Orange → *"Elite Mens SS Tee Medium Black/Orange"* |
| `ZCPSM-AS-M-B0` | Premium · Shorts · Mens · Medium · Black/Orange → *"Premium Mens Shorts Medium Black/Orange"* |
| `ZCPPM-AP-L-B0` | Premium · Pants · Mens · Large · Black/Orange → *"Premium Mens Pants Large Black/Orange"* |

## 4. Facilities & stores

### Distribution centers (facilities) — 7
| Code | Name | City | State |
|------|------|------|-------|
| `FC-MEM` | Zava Memphis Distribution Center | Memphis | TN |
| `FC-CLT` | Zava Charlotte Distribution Center | Charlotte | NC |
| `FC-SEA` | Zava Seattle Distribution Center | Seattle | WA |
| `FC-DFW` | Zava Dallas Distribution Center | Dallas | TX |
| `FC-EWR` | Zava Newark Distribution Center | Newark | NJ |
| `FC-RNO` | Zava Reno Distribution Center | Reno | NV |
| `FC-CMH` | Zava Columbus Distribution Center | Columbus | OH |

### Flagship retail stores (B2C) — 3
`ST-AUS` Zava Austin · `ST-MIA` Zava Miami · `ST-CHI` Zava Chicago

## 5. Inventory model

Inventory is tracked **per SKU per facility** with: `on_hand`, `reserved`, `available`, `reorder_point`,
`safety_stock`, `projected_stockout_days`, and a derived **status**:

- **critical** — `on_hand < 0.2 × reorder_point` **or** `projected_stockout_days ≤ 3`
- **low stock** — `on_hand < reorder_point`
- **in stock** — otherwise

**Planted hero alert (matches the reference UI):** at **Charlotte** (`FC-CLT`), SKU **`ZCPTM-LS-L-RR`**
("ZavaCore Field Premium LS Top") has **15 units**, **reorder point 80**, **projected stock-out in 3 days**
→ *critical, most urgent*.

## 6. Order tracking model (delivery)

Orders use **numeric IDs** (e.g., `23518`) and carrier tracking like `ZVX-7489201374829`. Fields (mirrors
the reference UI card): `order_id`, `recipient_name`, `carrier`, `tracking_number`, `status` (machine) +
`status_label` (display, e.g. *"Delayed - Weather"*), `estimated_delivery`, `last_location`
(a distribution-center name), `delivering_to` (city/state/zip), `delay_reason`, `notes`, `last_updated`.

- **Carriers:** `Zava Express`, `Swift Post`, `Metro Freight`.
- **Statuses / labels:** `processing`, `in_transit` (*In Transit*), `out_for_delivery` (*Out for Delivery*),
  `delivered` (*Delivered*), `delayed` (*Delayed - Weather* / *Delayed - Customs* / *Delayed - Volume*),
  `exception` (*Exception - Address* / *Exception - Damaged*).

### Hero orders (stable, referenced by notebooks/UI)
| Order | Status label | Recipient | Deliver to | Notes |
|-------|--------------|-----------|-----------|-------|
| `23518` | Delayed - Weather | Jane Smith | Seattle, WA 98101 | Held at **Zava Memphis Distribution Center**; severe winter storm; ETA 2026-02-17; *no action required*. |
| `23544` | Delayed - Customs | Marcus Lee | Toronto, ON M5H 2N2 | Held at customs; may need import documents; contacted by Zava Global support; ETA 2026-02-20. |
| `23561` | Out for Delivery | Priya Nair | Austin, TX 78701 | On the delivery vehicle; ETA today. |
| `23575` | Exception - Address | Diego Santos | Miami, FL 33101 | Address could not be verified; awaiting customer confirmation. |
| `23590` | Delivered | Sara Kim | Chicago, IL 60601 | Delivered and signed for. |

**As-of date for the demo:** `2026-02-15` (matches the reference UI timestamps).

## 7. Personas

| Persona | Role | Uses |
|---------|------|------|
| **Maya Alvarez** | Inventory Operations Manager | **InventoryAgent** — critical/low stock, on-hand, reorder, policies, analytics |
| **Tom Becker** | Distribution Center Lead (Charlotte) | InventoryAgent — per-facility stock & alerts |
| **Jane Smith / Priya Nair / Diego Santos** | Customers | **DeliverySupport Agent** — order tracking & delivery issues |

## 8. Demo scenarios

### InventoryAgent (prompt agent)
1. **Critical alerts (MCP → API):** *"What are my most critical stock issues right now?"*
   → *"…4 critical alerts; the most urgent is Charlotte with only 15 units of ZavaCore Field Premium LS
   Top (reorder point 80), projected to stock out in 3 days."*
2. **Live stock (MCP → API):** *"How many units of `ZCPTM-SS-S-B0` do we have across facilities?"*
3. **Per-facility (MCP → API):** *"Which SKUs are critical at Charlotte?"*
4. **On-hand by line (MCP → API):** *"What's the total on-hand units for the Premium line?"*
5. **Policy (Foundry IQ / AI Search):** *"What's our return policy for opened apparel / worn items?"*
6. **Analytics (Fabric IQ / Data Agent):** *"How did Elite line sales this month compare to last month?"*

### DeliverySupport Agent (hosted, Microsoft Agent Framework)
1. **Track (lookupOrder):** *"Hey, what's the status of order `23518`?"*
2. **Delay + memory (lookupOrder):** *"Why is `23544` delayed?"* → *"When will it arrive?"*
3. **Exception (lookupOrder):** *"My order `23575` says exception — what do I do?"*
4. **Voice-live:** the same order-tracking flow, spoken.

## 9. Knowledge-base documents (Foundry IQ / Azure AI Search) — `data/docs/`

Apparel-appropriate docs: inventory & reorder policy, returns & exchange policy (apparel/worn-item rules,
size exchanges), shipping & delivery SLA (carriers, weather/customs handling), distribution-center
operations manual, sizing & fabric-care guide, product-line overview (Core/Pro/Premium/Elite), and a
customer support FAQ (tracking, delays, exceptions, returns).

## 10. Structured data (Fabric semantic model) — `data/structured/`

`product_lines`, `products` (576), `facilities` (7), `stores` (3), `customers`, `inventory`
(per SKU × facility), `sales`, `orders`, `order_items`. The Fabric Data Agent answers analytical
questions (sales by line/gender/garment, category performance, fulfillment KPIs) over the semantic model.
