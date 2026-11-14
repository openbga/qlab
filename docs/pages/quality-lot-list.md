---
title: Material lots
urls: quality:lot_list
views: quality.views.lot_list
templates: quality/lot_list.html
models: quality.Lot, quality.LotReceipt, suppliers.Supplier, core.RuleSet
reviewed: 2026-11-14
---

## Purpose

The home page. Lists every manufacturing material lot so you can find a lot, open its record and start a new lot in quarantine.

## Who can use it

- Sign-in required; signed-out visitors go to the sign-in page.
- Viewing lot data requires one of the roles **analyst**, **reviewer**, **quality**, **admin** or **auditor**. On opening the workspace, signed-in accounts without these roles are sent to [Account access](/accounts/access/), which explains missing roles. Superuser status does not bypass this check.
- **New material lot** is shown only to **analysts**. Admin-only and other viewers cannot open or submit it; direct requests receive 403.

## Layout

- **Shared top bar**: the certificate-and-leaf mark and **Fresh COA** label link to Material lots. Menu opens navigation; on phones it is an icon named "Menu". Theme, Sign out and Page documentation remain available at the right. The brand text may shorten visually on a narrow screen.
- **Header**: title "Material lots" and the **New material lot** button for analysts, with a short description below.
- **Search**: the labelled **Find lot** box (placeholder "Lot, supplier lot or manufacturer lot"), **Search**, and **Clear filters** when a search is set.
- **Lots table**: columns Lot, Status, Material, Supplier, Supplier lot, Received, Rule set. Lot numbers link to the lot record; status has a text label and indicator. A lot without receipt details shows "Receipt not recorded" across the Supplier, Supplier lot and Received columns.
- **Empty states**: "No material lots yet" with "Receive a lot to start the quality journey." Analysts also see **New material lot**. A search with no matches shows "No material lots match these filters", "Search covers lot numbers and the supplier and manufacturer lot numbers of the current receipt details. Change the search or clear the filters." and **Clear filters**.
- **Source code**: the shared application footer links to the source repository configured for this deployment, [openbga/fresh-coa-lims](https://github.com/openbga/fresh-coa-lims) by default.
- **Footer**: "Showing X–Y of N material lots", with "matching filters" when searched. When there is more than one page, **Previous**, "Page N of M" and **Next** appear; unavailable directions are disabled.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| **New material lot** | Analyst role | Analyst | Opens the New material lot form |
| **Source code** | Always | Any viewer | Opens the configured source repository |
| **Search** | Always | Any viewer | Reloads the list filtered by the search text, from page 1 |
| **Clear filters** | A search is set | Any viewer | Removes the search and returns to the first page |
| Lot number link | One per row | Any viewer | Opens the lot record |
| **Previous** / **Next** | More than one page; enabled when that direction exists | Any viewer | Moves one page; keeps the search text |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Find lot (`q`) | — | Text | No | Case-insensitive partial match on the lot number, or on the supplier lot number or manufacturer lot number of the lot's current receipt details |
| Lot | `Lot.number` | Text, max 80, unique | — | Lot identifier; link to the lot record |
| Material | `Lot.material` | Text, max 160 | — | Material name as received |
| Supplier | `LotReceipt.supplier` → `Supplier.name`, else `LotReceipt.source` | Text | — | Name of the supplier on the current receipt details; "Made on site" for a lot made on site |
| Supplier lot | `LotReceipt.supplier_lot` | Text, max 80 | — | Supplier lot number on the current receipt details; "Not known" when the supplier's lot number is blank, "—" for a lot made on site |
| Received | `LotReceipt.received_on` | Date | — | Date received on the current receipt details |
| Rule set | `Lot.rules` → `RuleSet.code`, `RuleSet.version` | Shown as "code vN" | — | The approved rule revision chosen at receipt. It is not the lot's specification or sampling requirements, which are assigned afterwards |
| Status | `Lot.state` | Text: Quarantine, Released | — | Quarantine until a signed QC disposition releases the lot |

## Rules and hidden logic

- **Scope**: all lots in every state are listed; there is no status filter and no per-user restriction.
- **Search**: matches anywhere in the lot number (`LOT-TEST` finds `LOT-TEST-001`), or anywhere in the supplier lot number or manufacturer lot number of the lot's current receipt details. Receipt records replaced by a correction are not searched. Supplier name, material and rule set are not searched. Leading and trailing spaces are ignored.
- **Receipt columns**: Supplier, Supplier lot and Received come from the lot's current receipt details, the record that no correction has replaced. The manufacturer lot number is searched but not shown; open the lot record to see it.
- **Receipt not recorded**: shown for a lot received before receipt details were kept. An analyst can record them from the lot record while the lot is in Quarantine.
- **Order**: newest lot record first (`Lot.created_at` descending), not by the Received date.
- **Paging**: 30 lots per page. An out-of-range page number shows the last page; a non-numeric one shows page 1.
- **Status**: a new lot always starts in **Quarantine**. **Released** is set only by a signed lot disposition. No other states exist in this version.
- **Requirements**: the list does not show whether approved specification and sampling requirements are assigned; open the lot record to see its assignment status.
- **Role rule**: the creation button is hidden without the analyst role, and the server independently checks that role.

## Related pages

- New material lot: receive a lot in quarantine with its receipt details.
- Lot record: receipt details, samples, results, review and disposition.
- [Suppliers](/suppliers/): the register that receipt details name suppliers from.
- [Rule sets](/rules/): approved rule revisions that lots are received under.
