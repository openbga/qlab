---
title: Record receipt details
urls: quality:receipt_new
views: quality.views.receipt_new
templates: catalog/form.html
models: quality.LotReceipt, quality.Lot, suppliers.Supplier
reviewed: 2026-11-14
---

## Purpose

Adds receipt details to a quarantined lot that has none: a lot received before receipt details were kept. A lot received through New material lot already has them.

## Who can use it

- Sign-in required. **analyst** role only; others receive 403 Forbidden. The lot record shows **Record receipt details** only to analysts, on a Quarantine lot without receipt details.
- The **admin** role alone does not grant this page: opening or submitting it returns 403 Forbidden. An administrator who also holds the analyst role acts with that role only, with no exception to the independence rules.
- Only a Quarantine lot without receipt details: otherwise no form is shown and you are redirected to the lot record with "Only quarantined lots accept receipt details." (lot no longer in Quarantine) or "Receipt details are already recorded; correct them instead." The server repeats both checks on submission.

## Layout

- **Breadcrumbs**: Material lots, lot number, Record receipt details.
- **Intro**: "This lot was received before receipt details were kept. Record them from the delivery documents."
- **Record card**: Lot, Material, Status.
- **Form sections**: Source, Delivery, Examination on receipt, Change control.
- **Buttons**: **Cancel** (to the lot record) and **Record receipt details**.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| **Record receipt details** | Always | Analyst | Adds the receipt record, shows "Receipt details recorded." and returns to the lot record |
| **Cancel** | Always | Analyst | Returns to the lot record without saving |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Source | `LotReceipt.source` | Received from a supplier, Made on site | Yes | Where the lot came from. The menu opens on "—"; choose one. |
| Supplier | `LotReceipt.supplier` | Choice of every supplier in the register, shown as "code · name" | Conditional | Required for a lot received from a supplier; blank for one made on site. Help: "Required for a lot received from a supplier. A quality user adds suppliers to the register." |
| Supplier lot number | `LotReceipt.supplier_lot` | Text, max 80 | No | Help: "As printed on the supplier's label or documents. Leave blank if not known." Blank for material made on site. |
| Manufacturer | `LotReceipt.manufacturer` | Text, max 160 | Conditional | Help: "The manufacturer, when it is not the supplier and is known." Required when a manufacturer location or lot number is given. Blank for material made on site. |
| Manufacturer location | `LotReceipt.manufacturer_location` | Text, max 160 | No | Blank for material made on site. |
| Manufacturer lot number | `LotReceipt.manufacturer_lot` | Text, max 80 | No | Blank for material made on site. |
| Delivery or batch document | `LotReceipt.shipment_ref` | Text, max 120 | Yes | Help: "Delivery note, packing list or purchase order. For material made on site, the batch record or production order." |
| Date received | `LotReceipt.received_on` | Date | Yes | Prefilled with today's date; cannot be in the future. |
| Quantity received | `LotReceipt.quantity` | Decimal, above 0, at most 4 decimals and 10 digits before the point | Yes | Exact quantity that arrived. |
| Quantity unit | `LotReceipt.quantity_unit` | mg, g, kg, mL, L, units (items) | Yes | Unit of the quantity. The menu opens on "—"; choose one. |
| Number of containers | `LotReceipt.containers` | Integer, at least 1 | Yes | How many containers arrived. |
| Containers | `LotReceipt.container_description` | Text, max 160 | Yes | Help: "Type and size, e.g. 25 kg fibre drums." |
| Examination on receipt | `LotReceipt.condition` | No discrepancy found, Discrepancy found | Yes | Help: "Labels, seals, container condition and delivery documents, as your receiving procedure requires." The menu opens on "—"; state the outcome. |
| Examination notes | `LotReceipt.condition_notes` | Text, max 2000 | Conditional | Help: "Required when a discrepancy was found: what was wrong and with which containers." |
| Reason | `LotReceipt.reason` | Text, max 2000 | Yes | Why the details are recorded now; stored on the receipt record and in the audit event. |

## Rules and hidden logic

- **Supplier source**: "Select the supplier the lot was received from." when Source is "Received from a supplier" and no supplier is chosen.
- **Made on site**: "Material made on site has no supplier, supplier lot or outside manufacturer." when Source is "Made on site" and Supplier, Supplier lot number, Manufacturer, Manufacturer location or Manufacturer lot number is filled in.
- **Manufacturer**: "Name the manufacturer when giving its location or lot number."
- **Date received**: "The date received cannot be in the future." The date is compared with today's date in the deployment time zone.
- **Quantity**: "Enter an exact quantity greater than zero." for zero or a negative value; "Ensure that there are no more than 4 decimal places." for more decimals.
- **Containers**: "Ensure this value is greater than or equal to 1."
- **Discrepancy**: "Describe the discrepancy found on receipt." when the examination is "Discrepancy found" and the notes are blank.
- **Spaces**: spaces around text values are removed before saving.
- **Repeated by the server**: every rule is checked again under the lot lock when saving. For cases the form already stops, the server's own messages are "Choose where the lot came from.", "Enter the date the lot was received.", "Enter the number of containers received, at least one.", "Enter the delivery or batch document.", "Describe the containers." and "A reason is required."
- **Once, in quarantine**: the lot is locked while saving. "Only quarantined lots accept receipt details." and "Receipt details are already recorded; correct them instead." also apply if the lot changed after the page opened. A released lot without receipt details stays without them.
- **Effect**: one receipt record is added with you as recorder, the lot's record revision increases by 1, and audit event `lot.receipt_recorded` stores the details and your reason. A disposition signing page opened earlier then fails as stale.
- **Independence**: recording receipt details makes you an author of the lot's receipt data. You cannot sign this lot's disposition, even with the quality role.
- **Append-only**: a receipt record cannot be edited or deleted, and the database refuses a receipt record for a lot that is not in quarantine. Later changes go through Correct receipt details.
- **Not enforced by this page**: the supplier is not checked for qualification or approval; the receipt details do not change which tests the lot requires; "Discrepancy found" does not place a hold on the lot. Place a hold from Holds if the lot must not be dispositioned.
- Unknown lot: 404.
- **Form behaviour**: the page shows "Fields marked * are required. The change is recorded in the audit trail with your reason." An invalid or refused submission returns the form with status 422, keeps your entries and shows an error summary ("Check the highlighted field(s) below. Your entries were kept."). Refusals from the server appear beside the field they concern, or in the summary when they concern the whole form.

## Related pages

- Lot record.
- Correct receipt details.
- [Suppliers](/suppliers/)
- [Holds](/stability/holds/)
- [Material lots](/)
