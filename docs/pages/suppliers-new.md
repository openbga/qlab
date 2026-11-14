---
title: New supplier
urls: suppliers:new
views: suppliers.views.supplier_new
templates: catalog/form.html
models: suppliers.Supplier
reviewed: 2026-11-14
---

## Purpose

Adds a supplier to the register so that the receipt details of a lot can name it.

## Who can use it

- Sign-in required. **quality** role only; others receive 403 Forbidden.
- The **admin** role alone does not grant this page: opening or submitting it returns 403 Forbidden. An administrator who also holds the quality role acts with that role only.

## Layout

- **Breadcrumbs**: Suppliers, New supplier.
- **Intro**: "A supplier's identity cannot be edited after creation; use synthetic names only. Adding a supplier does not qualify it."
- **Form sections**: Supplier, Change control.
- **Buttons**: **Cancel** (to Suppliers) and **Create supplier**.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| **Create supplier** | Always | Quality | Creates the supplier, shows "Supplier <code> created." and opens the supplier record |
| **Cancel** | Always | Quality | Returns to Suppliers without saving |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Code | `Supplier.code` | Slug (letters, numbers, hyphens, underscores), max 60, unique | Yes | Help: "Short stable identifier, e.g. sup-syn-001." |
| Name | `Supplier.name` | Text, max 160 | Yes | Supplier name. |
| Location | `Supplier.location` | Text, max 160 | Yes | Help: "Site the material is supplied from: town and country." |
| Reason | audit event reason | Text, max 2000 | Yes | Stored in the audit event. |

## Rules and hidden logic

- **Code**: "This supplier code already exists." If another request saves the same code at the same moment (for example a double submission), the page shows "Another request saved a conflicting record at the same time. Reload and try again." and nothing is created.
- **Spaces**: spaces around the name and location are removed.
- **Immutable**: after creation the code, name and location cannot be edited or deleted (database trigger).
- **Audit**: `supplier.created` with the code, name, location and your reason. No signature or approval step applies to suppliers.
- **Not enforced by this page**: adding a supplier records who it is. It does not record or check that the supplier is qualified or approved, and it does not change which tests a lot requires.
- Assumption: supplier names should be synthetic in this environment, as the intro states; the page does not check the content.
- **Form behaviour**: the page shows "Fields marked * are required. The change is recorded in the audit trail with your reason." An invalid or refused submission returns the form with status 422, keeps your entries and shows an error summary ("Check the highlighted field(s) below. Your entries were kept.") plus refusals from the server as form-level errors.

## Related pages

- [Suppliers](/suppliers/)
- Supplier record (opened after saving).
