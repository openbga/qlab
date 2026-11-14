---
title: Supplier record
urls: suppliers:detail
views: suppliers.views.supplier_detail
templates: suppliers/detail.html
models: suppliers.Supplier, quality.LotReceipt, quality.Lot, core.AuditEvent
reviewed: 2026-11-14
---

## Purpose

Shows one supplier's identity, the lots whose current receipt details name it, and the history of the supplier record.

## Who can use it

- Sign-in required. Viewing requires one of **analyst**, **reviewer**, **quality**, **admin** or **auditor**; others receive 403 Forbidden.
- The page is read-only for every role: a supplier has no edit, retire or delete action.

## Layout

- **Breadcrumbs**: Suppliers, supplier code. Title: the supplier code, with the supplier name below it.
- **Supplier** card: Code, Name, Location, Qualification (always "Not recorded in this register") and Created (date, time and time zone, then "by" and the user who added it).
- **Lots received** card: table with Lot, Status, Material, Supplier lot, Manufacturer lot, Received and Quantity. Footer "Showing X–Y of N lots", with **Previous**, "Page N of M" and **Next** when there is more than one page. Empty: "No lots received from this supplier" ("Lots appear here when their current receipt details name this supplier.").
- **History** card: the audit events of the supplier record, oldest first, each with the event name (`supplier.created`), time, reason and user. "No recorded history." when there are none.
- **Foot line**: the supplier code, then "Viewed" with the time and your name.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| Lot number link | One per row | Any viewer | Opens the lot record |
| **Suppliers** (breadcrumb) | Always | Any viewer | Returns to the register |
| **Previous** / **Next** | More than one page of lots | Any viewer | Moves one page |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Code | `Supplier.code` | Text | — | Identifier; also the page title. |
| Name | `Supplier.name` | Text | — | Supplier name. |
| Location | `Supplier.location` | Text | — | Site the material is supplied from. |
| Qualification | — | Fixed text | — | "Not recorded in this register" for every supplier. |
| Created | `Supplier.created_at`, `Supplier.created_by` | Date and time; user | — | Full name, or the username when no name is set. |
| Lot | `LotReceipt.lot` → `Lot.number` | Link | — | Lot received from this supplier. |
| Status | `Lot.state` | Quarantine, Released | — | Current lot status. |
| Material | `Lot.material` | Text | — | Material name as received. |
| Supplier lot | `LotReceipt.supplier_lot` | Text | — | "Not known" when blank. |
| Manufacturer lot | `LotReceipt.manufacturer_lot` | Text | — | "—" when blank. |
| Received | `LotReceipt.received_on` | Date | — | Date received. |
| Quantity | `LotReceipt.quantity`, `LotReceipt.quantity_unit` | Decimal with unit | — | Exact quantity received, without trailing zeros. |
| History entry | `AuditEvent.action`, `occurred_at`, `reason`, `actor` | Text, date and time, user | — | What happened to the supplier record, when, why and by whom. |

## Rules and hidden logic

- **Lots listed**: one row per lot whose current receipt details name this supplier. A receipt record that a correction replaced is not used, so a lot corrected to another supplier, or to "Made on site", leaves this list. The replaced record stays in the Receipt history on the lot record.
- **Order**: latest date received first; lots received on the same date are ordered latest recorded first.
- **Paging**: 25 lots per page; `per_page` accepts 25, 50 or 100.
- **History**: shows events of the supplier record only. Receipt events of the lots are on each lot record and in the Audit trail.
- **Immutable**: the code, name and location cannot be edited or deleted (database trigger).
- **Not enforced by this page**: the register does not record whether the supplier is qualified or approved, and nothing checks it. Being listed here does not change which tests a lot requires or what its disposition needs.
- Unknown supplier: 404.

## Related pages

- [Suppliers](/suppliers/)
- Lot record (from a lot number).
- [Audit trail](/audit/)
