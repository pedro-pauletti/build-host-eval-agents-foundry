# Zava Engineering & Change-Management Policy (ZEP-1)

**Audience:** all engineers and automated agents that propose or approve code changes to Zava
production services (inventory, reorder, order, delivery). **Owner:** Zava Platform Engineering.

This policy is the checklist the **Compliance Agent** applies when reviewing a proposed fix during
incident response. A change is **APPROVED** only when every applicable rule is satisfied; otherwise it
is returned as **NEEDS-CHANGES** with specific reasons.

## 1. Correctness & tests
- **C1.** Every change to business logic must be covered by automated tests, and **all tests must pass**
  (`pytest` green). A change that leaves any test failing is never approved.
- **C2.** Fixes must address the **root cause**, not mask symptoms (e.g. do not silence a failing test,
  delete assertions, or hard-code expected outputs).
- **C3.** Changes must be **minimal and scoped** to the incident. Unrelated refactors, renames, or
  behavioural changes are not permitted in an incident fix.

## 2. Business invariants (reorder service)
- **B1.** A reorder quantity must **never be negative**.
- **B2.** When `on_hand` is above the SKU's `reorder_point`, the reorder quantity must be **exactly 0**.
- **B3.** Reorder quantities must be ordered in **whole supplier case packs** and rounded **up** so that
  `on_hand + reorder_quantity >= target_level` for any SKU at or below its reorder point.
- **B4.** Existing validation guards (e.g. the non-negative-quantity check) must **not** be removed or
  weakened to make a batch pass.

## 3. Security & safety
- **S1.** No secrets, tokens, credentials, or connection strings in source or logs.
- **S2.** No new outbound network calls, subprocess execution, or file-system writes introduced into a
  pure calculation module (such as `reorder.py`).
- **S3.** No collection or logging of customer PII in reorder/inventory code paths.

## 4. Change management & auditability
- **M1.** The change must include a **clear summary** of what was wrong and what was fixed.
- **M2.** The proposed diff must be **reviewable** (small, readable, and limited to the affected files).
- **M3.** High-severity incident fixes require an explicit compliance **sign-off** before the batch is
  re-run in production.

## 5. Decision format
The Compliance Agent returns:
- **decision:** `approved` or `needs-changes`
- **checks:** the rule IDs evaluated, each `pass` / `fail` / `n/a`
- **rationale:** a short, plain-language justification citing the failing rule IDs (if any)
- **required_changes:** a list of concrete fixes needed for approval (empty when approved)
