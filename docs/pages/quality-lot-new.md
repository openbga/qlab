---
title: New material lot
urls: quality:lot_new
views: quality.views.lot_new
templates: catalog/form.html
models: quality.Lot, quality.LotReceipt, suppliers.Supplier, core.RuleSet
reviewed: 2026-11-14
---

## Purpose

Receive a manufacturing material lot into quarantine under an approved rule set, together with the details of its receipt: where it came from, what arrived and what the examination on receipt found.

## Who can use it

- Sign-in required. **analyst** role only; others receive 403 Forbidden. Material lots shows the **New material lot** button only to analysts.
- The **admin** role alone does not grant this page: opening or submitting it returns 403 Forbidden. An administrator who also holds the analyst role acts with that role only, with no exception to the independence rules.

## Layout

- **Breadcrumbs**: Material lots, New material lot.
- **Intro**: "Receive a lot into quarantine with the details of its receipt: where it came from, what arrived and what the examination on receipt found."
- **Form sections**: Lot, Source, Delivery, Examination on receipt, Change control.
- **Buttons**: **Cancel** (to Material lots) and **Receive lot**.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| **Receive lot** | Always | Analyst | Creates the lot in Quarantine with its receipt details, shows "Lot received in quarantine." and opens the lot record |
| **Cancel** | Always | Analyst | Returns to Material lots without saving |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Lot number | `Lot.number` | Text, max 80, unique | Yes | Lot identifier. |
| Material | `Lot.material` | Text, max 160 | Yes | Material name. |
| Rule set | `Lot.rules` | Choice of approved rule revisions, shown as "code vN" | Yes | Rule set that fixes the required tests for this lot. |
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
| Reason | `LotReceipt.reason` | Text, max 2000 | Yes | Why the lot is being received; stored on the receipt record and in both audit events. |

## Rules and hidden logic

- **Not the release requirements**: choosing a rule set does not assign approved specification or sampling requirements and does not show the lot is ready for testing. Requirements are assigned afterwards on Lot requirements and sampling; the rule set's required-test list is only part of the foundation path, not the whole native release gate.
- **Rule choices**: only rule revisions with status approved are offered. The chosen revision must also be effective now, else "An approved, effective rule revision is required."
- **Lot number**: "This lot number already exists." when the number is taken (exact match). If another request saves the same lot number at the same moment (for example a double submission), the page shows "Another request saved a conflicting record at the same time. Reload and try again." and nothing is created.
- **Supplier source**: "Select the supplier the lot was received from." when Source is "Received from a supplier" and no supplier is chosen.
- **Made on site**: "Material made on site has no supplier, supplier lot or outside manufacturer." when Source is "Made on site" and Supplier, Supplier lot number, Manufacturer, Manufacturer location or Manufacturer lot number is filled in.
- **Manufacturer**: "Name the manufacturer when giving its location or lot number."
- **Date received**: "The date received cannot be in the future." The date is compared with today's date in the deployment time zone.
- **Quantity**: "Enter an exact quantity greater than zero." for zero or a negative value; "Ensure that there are no more than 4 decimal places." for more decimals.
- **Containers**: "Ensure this value is greater than or equal to 1."
- **Discrepancy**: "Describe the discrepancy found on receipt." when the examination is "Discrepancy found" and the notes are blank.
- **Spaces**: spaces around text values are removed before saving.
- **Repeated by the server**: every receipt rule is checked again when saving. For cases the form already stops, the server's own messages are "Choose where the lot came from.", "Enter the date the lot was received.", "Enter the number of containers received, at least one.", "Enter the delivery or batch document.", "Describe the containers." and "A reason is required."
- **All or nothing**: the lot and its receipt details are saved together. If either is refused, neither is created.
- **Defaults**: state Quarantine, revision 1, received by the signed-in user at the server time.
- **Audit**: writes `lot.received` with number, material and rule set, and `lot.receipt_recorded` with the receipt details. Both carry your reason.
- **Independence**: you are stored as the recorder of the receipt details. That makes you an author of the lot's receipt data: you cannot sign this lot's disposition, even with the quality role.
- **Append-only**: the receipt record cannot be edited or deleted. While the lot is in quarantine an analyst can correct it with Correct receipt details on the lot record; the original is kept.
- **Not enforced by this page**: the supplier is not checked for qualification or approval; the receipt details do not change which tests the lot requires; "Discrepancy found" does not place a hold on the lot. Place a hold from Holds if the lot must not be dispositioned.
- **Form behaviour**: the page shows "Fields marked * are required. The change is recorded in the audit trail with your reason." An invalid or refused submission returns the form with status 422, keeps your entries and shows an error summary ("Check the highlighted field(s) below. Your entries were kept."). Refusals from the server appear beside the field they concern, or in the summary when they concern the whole form.

## Related pages

- [Material lots](/)
- Lot record (opened after saving).
- [Suppliers](/suppliers/)
- [Rule sets](/rules/)
- [Holds](/stability/holds/)
- Assign requirements to a lot (after receipt).
- Correct receipt details (from the lot record).
