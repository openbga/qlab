---
title: Lot record
urls: quality:lot_detail
views: quality.views.lot_detail
templates: quality/lot_detail.html
models: quality.Lot, quality.LotReceipt, quality.Sample, quality.Result, suppliers.Supplier, core.RuleSet, core.ElectronicSignature, sampling.LotAssignment, reporting.Report
reviewed: 2026-11-14
---

## Purpose

The hub for one material lot: its facts, receipt details and samples, links to its requirements, sampling and native testing, the signed QC disposition that releases it, and its certificates of analysis.

## Who can use it

- Sign-in required. Viewing requires one of **analyst**, **reviewer**, **quality**, **admin** or **auditor**; others receive 403.
- **Add sample** and **Record result**: analysts only.
- **Record receipt details** and **Correct receipt details**: analysts only, while the lot is Quarantine. Other roles do not see them and receive 403 if they open those pages directly.
- **Review result**: reviewers only, and never the analyst who recorded that result.
- **Review disposition** and **Issue certificate of analysis**: quality role only.
- Scientific action links require their corresponding role as well as the state condition. Admin-only viewers see records and navigation links, without laboratory mutation controls. The server independently checks roles, independence and state.

## Layout

- **Back link**: "Material lots".
- **Facts**: Material, Status, Rule set, Record revision.
- **Actions row** (Quarantine lots only): **Add sample**, **Review disposition**.
- **Requirements line**: **Requirements and sampling** with the assignment status ("Requirements assigned", "Applicability hold" or "Not assigned"), and **Testing and investigations**.
- **Receipt** card, header: for analysts on a Quarantine lot, **Correct receipt details** when the lot has receipt details, otherwise **Record receipt details**.
- **Receipt** card, details: Source; for a lot received from a supplier also Supplier (code, name and location), Supplier lot number ("Not known" when blank), Manufacturer (name and location, or "Not stated") and Manufacturer lot number (only when recorded); then Delivery or batch document, Date received, Quantity received, Containers (number, then description) and Examination on receipt (the label "No discrepancy found" or "Discrepancy found", with the examination notes below it).
- **Receipt** card, discrepancy note: when a discrepancy was found, "A discrepancy does not hold the lot by itself. Place a hold from Holds if the lot must not be dispositioned until it is resolved.", with a link to Holds.
- **Receipt history** (inside the card): every receipt record of the lot, oldest first. Each entry shows "Receipt recorded" or "Receipt details corrected", the time, the reason and "Recorded by" with the user. A correction also lists each changed detail as old value → new value; an empty value reads "blank".
- **Receipt** card without details: "Receipt details are not recorded: this lot was received before they were kept." On a Quarantine lot it adds "An analyst can record them while the lot is in quarantine."
- **Samples and results**: one card per sample with its collection time, a **Record result** link (Quarantine lots only) and the foundation results table: Test, Result, Limits, Analyst, Review. This table shows only manual foundation results; native observations, reviews and investigations are on Testing and investigations. "No results recorded." here does not mean no native testing exists. "No samples recorded." when the lot has no samples.
- **Certificates of analysis** (Released lots only): **Issue certificate of analysis** for quality users, then links to issued reports, or "No certificate issued yet."
- **Electronic signatures**: foundation result review signatures, then lot disposition signatures, or "No lot disposition signature yet." Native test review signatures are not listed here.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| **Add sample** | Analyst role and lot is Quarantine | Analyst | Opens Add sample for this lot |
| **Review disposition** | Quality role and lot is Quarantine | Quality, independent of the lot's data | Opens Sign lot disposition |
| **Record receipt details** | Analyst role, lot is Quarantine and has no receipt details | Analyst | Opens Record receipt details for this lot |
| **Correct receipt details** | Analyst role, lot is Quarantine and has receipt details | Analyst | Opens Correct receipt details, prefilled with the current details |
| Supplier code link | Receipt details name a supplier | Any viewer | Opens the supplier record |
| **Holds** | Receipt details record a discrepancy | Viewers of that page | Opens the Holds list |
| **Requirements and sampling** | Always | Viewers of that page | Opens the lot's requirement assignment and sampling records |
| **Testing and investigations** | Always | Viewers of that page | Opens native tests, observations, reviews and investigations |
| **Record result** | Analyst role and lot is Quarantine | Analyst | Opens the development-only manual result form; saving is refused outside DEBUG or once requirements are assigned |
| **Review result** | Reviewer role, result is Recorded and not its analyst | Reviewer, not its analyst | Opens Sign result review |
| **Issue certificate of analysis** | Quality role and lot is Released | Quality | Opens the certificate preview for this lot |
| Report number link | Lot is Released and a report exists | Viewers of reports | Opens the certificate record |
| **Material lots** | Always | Any viewer | Returns to the list |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Lot number (heading) | `Lot.number` | Text | — | Lot identifier |
| Material | `Lot.material` | Text | — | Material received |
| Status | `Lot.state` | Quarantine, Released | — | Released only by signed disposition |
| Rule set | `Lot.rules` | "code vN" | — | Foundation rule revision chosen at receipt |
| Record revision | `Lot.revision` | Integer | — | Rises with each change to the lot, its samples, tests or holds, and when receipt details are recorded later or corrected; disposition signatures bind to it |
| Assignment status | `LotAssignment.status` (latest) | Requirements assigned, Applicability hold, or "Not assigned" | — | Whether approved specification and sampling requirements are attached |
| Source | `LotReceipt.source` | Received from a supplier, Made on site | — | Where the lot came from |
| Supplier | `LotReceipt.supplier` → `Supplier.code`, `name`, `location` | Link and text | — | Shown when the receipt names a supplier; the code opens the supplier record |
| Supplier lot number | `LotReceipt.supplier_lot` | Text | — | Shown with a supplier; "Not known" when blank |
| Manufacturer | `LotReceipt.manufacturer`, `manufacturer_location` | Text | — | Shown with a supplier; "Not stated" when blank |
| Manufacturer lot number | `LotReceipt.manufacturer_lot` | Text | — | Shown with a supplier, only when recorded |
| Delivery or batch document | `LotReceipt.shipment_ref` | Text | — | Delivery note, packing list or purchase order; for material made on site the batch record or production order |
| Date received | `LotReceipt.received_on` | Date | — | Date the lot arrived |
| Quantity received | `LotReceipt.quantity`, `quantity_unit` | Decimal with unit | — | Exact quantity, without trailing zeros |
| Containers | `LotReceipt.containers`, `container_description` | Integer and text | — | Number of containers, then their type and size |
| Examination on receipt | `LotReceipt.condition`, `condition_notes` | Label and text | — | No discrepancy found or Discrepancy found, with the notes |
| Receipt history entry | `LotReceipt.recorded_at`, `recorded_by`, `reason`, `corrects` | Date and time, user, text | — | One entry per receipt record; a correction is linked to the record it replaces |
| Sample heading | `Sample.reference` | Text, unique | — | Sample identifier |
| Collected | `Sample.collected_at` | Date and time | — | Labelled UTC; shown in the deployment time zone (default UTC) |
| Test, Result, Limits, Analyst, Review | `Result.test_code`, `value`, `unit`, `lower_limit`, `upper_limit`, `analyst`, `state` | Text, decimal with unit | — | Foundation manual results only; "Out of specification" when outside the inclusive limits |
| Report link | `Report.number` | Text | — | Issued certificates for this lot |
| Signature lines | `ElectronicSignature.object_id`, `revision`, `signer_name`, `meaning`, `signed_at` | Text, integer, date-time | — | Who signed which meaning, when, bound to which revision |

## Rules and hidden logic

- **Quarantine only**: samples, foundation results, receipt details and receipt corrections are accepted only while the lot is Quarantine ("Only quarantined lots accept new samples."; "Only quarantined lots accept receipt details."; "Only quarantined lots accept receipt corrections.").
- **Current receipt details**: the card shows the receipt record that no correction has replaced. Receipt records are append-only: none can be edited or deleted, and a correction adds a linked record. A lot has one original record and a single chain of corrections.
- **Lots without receipt details**: a lot received through New material lot always has them. Only a lot received before receipt details were kept has none; an analyst can add them while it is Quarantine, and a released lot stays without them.
- **Receipt history changes**: a correction compares Source, Supplier, Supplier lot number, Manufacturer, Manufacturer location, Manufacturer lot number, Delivery or batch document, Date received, Quantity received (with its unit), Number of containers, Containers, Examination on receipt and Examination notes, and lists only those that differ.
- **Discrepancy**: "Discrepancy found" is information only. It does not place a hold and does not block disposition; only an active hold does.
- **Not enforced by this page**: the supplier named on the receipt is not checked for qualification or approval, and the receipt details do not change which tests the lot requires.
- **Record result link vs. permission**: the link stays visible to analysts on Quarantine samples, but saving is refused with "Record observations through approved native testing requirements." unless the server runs in DEBUG and the lot has no requirement assignment. Record native results through Testing and investigations.
- **Release paths**: with assigned requirements or native tests (and always outside DEBUG), release depends on the assignment, sampling records, native analytical evidence and holds. The manual foundation path (required rule-set tests, reviewed and conforming results) applies only in DEBUG on lots with neither. See Sign lot disposition for every condition and message.
- **Revision and stale pages**: signing pages bind to the revision shown when opened (the result's for review, the lot's for disposition); if it changed, signing fails with "Record changed. Reload and review before signing." Recording receipt details on an earlier lot, or correcting them, raises the lot revision by 1.
- **Independence**: no user dispositions a lot containing their own receipt, sampling or test data, even when holding the quality role. Receipt data covers everyone who recorded or corrected the lot's receipt details, including the recorder of a record that was later corrected. **Review disposition** still shows for them; the disposition page explains the refusal before any PIN is requested.
- **No reject path**: this version only releases; a lot that cannot be released stays in Quarantine.
- **Review link after release**: a Recorded foundation result still shows **Review result** to independent reviewers on a released lot, but signing is refused ("This result is not awaiting review.").
- **Certificates**: the section appears only after release; issuing is a separate signed step on the certificate pages.

## Related pages

- [Material lots](/)
- Lot requirements and sampling; Lot testing (Testing and investigations).
- Record receipt details, Correct receipt details; Supplier record.
- Add sample, Record result, Sign result review, Sign lot disposition.
- Review certificate; Certificate record.
- [Suppliers](/suppliers/)
- [Holds](/stability/holds/)
- [Audit trail](/audit/)
