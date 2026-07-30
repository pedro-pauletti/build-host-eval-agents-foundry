# Shipping and Delivery SLA
This SLA describes Zava carriers, regional delivery windows, delay handling, customs support, and address-exception resolution.

## Carrier network and status flow
Zava ships ZavaCore Field apparel through three fictitious carrier services: Zava Express, Swift Post, and Metro Freight. Zava Express handles local and high-priority parcel routes. Swift Post handles standard domestic parcel delivery. Metro Freight is used for bulk retail replenishment, oversized fixtures, or large consolidated shipments rather than typical single-customer apparel parcels.

Customer orders use the status flow `processing → in_transit → out_for_delivery → delivered`. Exceptions include `delayed` with Weather, Customs, or Volume reason labels, and `exception` with Address or Damaged labels. Tracking should be explained from the Zava order record, not from any external website.

## Delivery windows by region
Domestic orders near the assigned distribution center generally deliver in 1 to 2 business days after shipment. Regional domestic orders generally deliver in 2 to 4 business days. Cross-country domestic orders generally deliver in 4 to 6 business days. International orders generally deliver in 6 to 10 business days after export release, excluding customs holds.

Zava's service-level goal is 96% on-time delivery for domestic parcel orders and 90% on-time delivery for international parcel orders. The clock begins when the order leaves `processing` and receives its first carrier movement scan.

## Weather and volume delays
Weather delays occur when storms, road closures, airport disruptions, or unsafe carrier operations slow movement. For order `23518`, the correct customer guidance is that the order is delayed by severe winter weather, held at Zava Memphis Distribution Center, and no customer action is required unless Zava later asks for updated delivery instructions.

Volume delays occur during launches, holiday peaks, regional events, or carrier capacity constraints. Customer support should provide the latest scan, revised estimated delivery date when available, and a follow-up commitment if the carrier has not updated within 2 business days.

## International and customs handling
International shipments may be delayed by customs inspection, import-document review, duty assessment, or recipient verification. For order `23544`, the order is delayed at customs and may require import documents. Zava Global support is responsible for contacting the customer, collecting any required information, and coordinating with the carrier.

Customers should not be asked to create their own commercial invoice. Zava prepares export and import-support documentation from the order record. If the destination authority requests additional recipient details, support must document exactly what is needed and the deadline.

## Address exceptions and damage exceptions
An Address exception means the carrier cannot verify or complete delivery. For order `23575`, customer action is required: confirm street address, unit number, postal code, phone number, delivery access notes, and recipient name. Zava may correct minor details after verification, but major destination changes require identity review.

A Damaged exception means the shipment cannot continue safely or the package was reported damaged. Zava Customer Care decides whether to replace, refund, or wait for carrier inspection. Address exceptions should be resolved within 5 business days before the shipment may be returned to a distribution center.

---
**Document metadata**
- doc_id: ZAVA-SHIPPING-01
- category: policy
- audience: both
- last_updated: 2026-01-31
- owner: Zava Delivery Operations
