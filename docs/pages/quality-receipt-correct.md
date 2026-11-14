---
title: Correct receipt details
urls: quality:receipt_correct
views: quality.views.receipt_correct
templates: catalog/form.html
models: quality.LotReceipt, quality.Lot, suppliers.Supplier
reviewed: 2026-11-14
---

## Purpose

Corrects the receipt details of a quarantined lot by adding a linked, newer record. The record it replaces is kept and stays visible in the Receipt history on the lot record.

## Who can use it

- Sign-in required. **analyst** role only; others receive 403 Forbidden. Any analyst may correct, not only the one who recorded the details. The lot record shows **Correct receipt details** only to analysts, on a Quarantine lot that has receipt details.
- The **admin** role alone does not grant this page: opening or submitting it returns 403 Forbidden. An administrator who also holds the analyst role acts with that role only, with no exception to the independence rules.
- Only a Quarantine lot with receipt details: otherwise no form is shown and you are redirected to the lot record with "Only quarantined lots accept receipt corrections." (lot no longer in Quarantine) or "This lot has no receipt details to correct." The server repeats the quarantine check on submission.

## Layout

- **Breadcrumbs**: Material lots, lot number, Correct receipt details.
- **Intro**: "A correction adds a record and keeps the one it replaces. State what was wrong in the reason."
- **Record card**: Lot, Material, Status.
- **Form** prefilled with the current receipt details: sections Source, Delivery, Examination on receipt, Change control. The reason starts blank.
- **Buttons**: **Cancel** (to the lot record) and **Correct receipt details**.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| **Correct receipt details** | Always | Analyst | Adds the correction, shows "Receipt details corrected; the original is kept." and returns to the lot record |
| **Cancel** | Always | Analyst | Returns to the lot record without saving |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Source | `LotReceipt.source` | Received from a supplier, Made on site | Yes | Where the lot came from. |
| Supplier | `LotReceipt.supplier` | Choice of every supplier in the register, shown as "code · name" | Conditional | Required for a lot received from a supplier; blank for one made on site. Help: "Required for a lot received from a supplier. A quality user adds suppliers to the register." |
| Supplier lot number | `LotReceipt.supplier_lot` | Text, max 80 | No | Help: "As printed on the supplier's label or documents. Leave blank if not known." Blank for material made on site. |
| Manufacturer | `LotReceipt.manufacturer` | Text, max 160 | Conditional | Help: "The manufacturer, when it is not the supplier and is known." Required when a manufacturer location or lot number is given. Blank for material made on site. |
| Manufacturer location | `LotReceipt.manufacturer_location` | Text, max 160 | No | Blank for material made on site. |
| Manufacturer lot number | `LotReceipt.manufacturer_lot` | Text, max 80 | No | Blank for material made on site. |
| Delivery or batch document | `LotReceipt.shipment_ref` | Text, max 120 | Yes | Help: "Delivery note, packing list or purchase order. For material made on site, the batch record or production order." |
| Date received | `LotReceipt.received_on` | Date | Yes | Cannot be in the future. |
| Quantity received | `LotReceipt.quantity` | Decimal, above 0, at most 4 decimals and 10 digits before the point | Yes | Prefilled without trailing zeros. |
| Quantity unit | `LotReceipt.quantity_unit` | mg, g, kg, mL, L, units (items) | Yes | Unit of the quantity received. |
| Number of containers | `LotReceipt.containers` | Integer, at least 1 | Yes | How many containers arrived. |
| Containers | `LotReceipt.container_description` | Text, max 160 | Yes | Help: "Type and size, e.g. 25 kg fibre drums." |
| Examination on receipt | `LotReceipt.condition` | No discrepancy found, Discrepancy found | Yes | Help: "Labels, seals, container condition and delivery documents, as your receiving procedure requires." |
| Examination notes | `LotReceipt.condition_notes` | Text, max 2000 | Conditional | Help: "Required when a discrepancy was found: what was wrong and with which containers." |
| Reason for correction | `LotReceipt.reason` | Text, max 2000 | Yes | What was wrong; stored on the new record and in the audit event. |
| Receipt (hidden) | `LotReceipt.corrects` | Record ID | Yes | The receipt record the page showed when it opened. |

## Rules and hidden logic

- **Stale page**: if another correction was saved after you opened the page, the hidden record no longer matches the current one: "The receipt details changed. Reload and review them before correcting." Nothing is saved; reload the page to see the current details. The server checks this again under the lot lock, so two corrections of the same record cannot both apply.
- **No change**: "The correction changes nothing." when every detail equals the current record. Differences only in surrounding spaces or in trailing zeros of the quantity do not count as a change.
- **Any detail can change**, including the source and the supplier.
- **Same checks as recording**: "Select the supplier the lot was received from."; "Material made on site has no supplier, supplier lot or outside manufacturer."; "Name the manufacturer when giving its location or lot number."; "The date received cannot be in the future." (today's date in the deployment time zone); "Enter an exact quantity greater than zero."; "Ensure that there are no more than 4 decimal places."; "Ensure this value is greater than or equal to 1." (containers); "Describe the discrepancy found on receipt."
- **Quarantine only**: the lot is locked while saving; "Only quarantined lots accept receipt corrections." if it was released after the page opened. The receipt details of a released lot cannot be corrected.
- **Effect**: a new record linked to the one it replaces is added with you as recorder and becomes the current receipt details. The lot's record revision increases by 1, and audit event `lot.receipt_corrected` stores the details before and after with your reason. A disposition signing page opened earlier then fails as stale.
- **What is kept**: the replaced record is never changed. The lot record lists it in Receipt history, and the correction shows each changed detail as old value → new value.
- **Lists that follow the current details**: Material lots and the supplier records use the new record. A lot corrected to another supplier moves to that supplier's record.
- **Independence**: correcting makes you an author of the lot's receipt data, as does having recorded a record that was later replaced. None of these users can sign this lot's disposition, even with the quality role.
- **Append-only**: a receipt record cannot be edited or deleted, and the database refuses a receipt record for a lot that is not in quarantine or a correction linked to another lot's record.
- **Not enforced by this page**: the supplier is not checked for qualification or approval; the receipt details do not change which tests the lot requires; "Discrepancy found" does not place a hold on the lot. Place a hold from Holds if the lot must not be dispositioned.
- Unknown lot: 404.
- **Form behaviour**: the page shows "Fields marked * are required. The change is recorded in the audit trail with your reason." An invalid or refused submission returns the form with status 422, keeps your entries and shows an error summary ("Check the highlighted field(s) below. Your entries were kept."). Refusals from the server appear beside the field they concern, or in the summary when they concern the whole form.

## Related pages

- Lot record.
- Record receipt details (for a lot without receipt details).
- [Suppliers](/suppliers/)
- [Holds](/stability/holds/)
- [Material lots](/)
