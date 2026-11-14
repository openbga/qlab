---
title: Sign lot disposition
urls: quality:disposition
views: quality.views.sign
templates: signatures/sign.html, signatures/dialog.html
models: quality.Lot, quality.LotReceipt, quality.Sample, quality.Result, sampling.LotAssignment, sampling.SamplingRecord, analytical.AnalyticalTest, analytical.Observation, analytical.Investigation, stability.Hold, core.ElectronicSignature, core.PINCredential
reviewed: 2026-11-14
---

## Purpose

Record the signed QC disposition of a quarantined lot with meaning **approved**, which releases it. This is a QC disposition, not manufacturer release.

## Who can use it

- Sign-in required. **Quality** role only; others receive 403.
- Never a user who authored any of the lot's receipt, sampling or test data, even with the quality role (see Independence). Such a user sees the reason, a **Return to the lot** link and no signing form (status 403); no PIN is requested.
- Requires an enrolled signature PIN.

## Layout

- A signing dialog (a plain card without JavaScript): meaning, lot number, the lot record revision shown, the signer, the resulting revision the signature binds (shown + 1), a PIN enrolment link, the form, **Sign approved** and **Cancel**.
- For a data author, the same card shows the refusal in place of the form, without the dialog behaviour.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| **Sign approved** | You are not an author of the lot's receipt, sampling or test data | Quality, independent of the lot's data | Lot becomes Released; "Lot released."; returns to the lot record |
| **Cancel** / Escape | Always | Any | Returns to the lot record; nothing is signed |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Reason | `AuditEvent.reason` | Text, max 2000 | Yes | Disposition rationale |
| Signing username | — | Text | Yes | Must equal your own username; re-entered for every signature |
| Signature PIN | `PINCredential` (checked, never stored) | Masked digits | Yes | Re-entered for every signature; cleared after errors |
| Expected revision (hidden) | `Lot.revision` | Integer | Yes | Lot revision shown when the page opened |
| Frozen evidence (not shown) | `Lot.disposition_evidence` | JSON | — | Native path: assignment ID and hash plus the analytical evidence snapshot |

## Rules and hidden logic

- **Always checked first**: the lot is still Quarantine ("This lot has already been dispositioned."), has no active hold ("<hold> (<kind> hold) is active: <reason>"), and its rule set is still approved and effective ("An approved, effective rule revision is required."). These apply to both paths below.
- **Opening vs. signing**: the page opens for any quality user whatever the lot's state; the state, hold and evidence checks run only when you sign. The authorship check runs on opening too, so an author is told before entering a PIN.
- **Native path** (the lot has a requirement assignment or native tests; always outside DEBUG). Each failing condition is listed as its own message:
- *Native, requirements*: a current assignment with status Requirements assigned; none assigned or an applicability hold blocks.
- *Native, samples*: at least one ("The lot requires a sampled and tested record.").
- *Native, sampling provenance*: every sample has a current sampling record under the assigned plan revision; any sampling deviation needs an accepted independent assessment (pending or rejected blocks).
- *Native, analytical evidence*: no open test, none awaiting review, no nonconforming result (unless an investigation invalidated it) and no result against a superseded requirement, no open or confirmed investigation, and a reviewed conforming result for every required test on every sample.
- *Native, no mixed evidence*: foundation manual results on the lot block ("Mixed foundation and native evidence requires reconciliation.").
- *Native, frozen evidence*: on release the assignment ID and hash and the analytical evidence snapshot are stored on the lot.
- **Manual foundation path** (development only: DEBUG and neither assignment nor native tests): at least one sample ("The lot requires a sample and reviewed results."); all required rule-set tests per sample ("Required tests are missing."); every result Reviewed and conforming ("All results must conform and have independent review.").
- **Independence**: "You cannot disposition a lot containing your own receipt, sampling or test data." Authors are users who recorded or corrected the lot's receipt details, including the recorder of a record that a correction later replaced; sampled or recorded any sampling record of the lot, including corrected originals and intermediate corrections; recorded observations (including corrected originals), submitted tests, recorded batch QC, opened an investigation, or wrote investigative entries; and, on the manual path, the analysts of the results. Holding several roles never waives this. Writing rules or specifications, assigning requirements or tests, or signing reviews, assessments and conclusions is not authorship. The check is shown when the page opens and repeated under the lot lock when signing.
- **Receipt authors**: the receipt check applies on both the native and the manual path. The analyst who received the lot through New material lot recorded its receipt details and so cannot sign its disposition. The check reads the receipt records only: a lot received before receipt details were kept has no receipt author until an analyst records them.
- **Receipt details are not a release condition**: signing does not require receipt details to exist and does not read the examination on receipt. A recorded discrepancy blocks nothing by itself; only an active hold does. Not enforced by this page: whether the supplier named on the receipt is qualified or approved.
- **Stale page**: any new sample, test change or hold since opening, and receipt details recorded later or corrected, change the lot revision: "Record changed. Reload and review before signing."
- **Identity and PIN**: "Enter your own signing username and PIN." on a mismatch (audited as `signature.identity_denied`); "Enroll a signature PIN first."; "Signature PIN was not accepted."; 5 consecutive failures lock the PIN for 15 minutes ("Signature PIN is temporarily locked."). Failures are recorded (`signature.denied`) even though the disposition is refused.
- **Session**: defaults are a 15-minute idle and 8-hour absolute limit; sessions without recorded login times count as expired. On expiry the next request signs you out with "Your session expired. Sign in again to continue." The inline "Session expired. Sign in again before signing." is an extra safeguard at the moment of signing.
- **Effect**: one transaction sets Released, raises the lot revision by 1, writes `signed.approved` and stores an immutable signature (signer, meaning, server time, bound revision, content hash). There is no reject or reversal path in this version.

## Related pages

- Lot record.
- Lot requirements and sampling; Assess sampling deviation; Lot testing; Holds.
- Record receipt details; Correct receipt details.
- [Signature PIN](/signature-pin/)
