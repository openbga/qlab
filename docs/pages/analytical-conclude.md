---
title: Conclude investigation
urls: analytical:conclude
views: analytical.views.conclude
templates: analytical/sign.html, analytical/_summary.html
models: analytical.Investigation, analytical.AnalyticalTest, core.ElectronicSignature, core.PINCredential
reviewed: 2026-11-14
---

## Purpose

Quality signs the conclusion that closes an investigation: the original result is confirmed or invalidated for an assignable laboratory cause.

## Who can use it

- Sign-in required. **Quality** only; others receive 403.
- Never the user who opened the investigation, who generated data for the original or any linked test (observation recorders including superseded ones, submitters, batch QC recorders), or who authored an assessment, hypothesis, evidence or impact entry. Escalation and authorized-retest entries are not counted. These people are also barred from signing the lot's QC disposition, which additionally excludes whoever recorded or corrected the lot's receipt details and whoever sampled or recorded its sampling records.
- Requires an enrolled signature PIN.
- **Admin** alone, or a superuser without a lab role, receives 403 when opening the page or posting it; admin is not a scientific role. Admin together with the required role may act, subject to the same independence rules.

## Layout

- Card "Conclude INV-n": "Your signature records concluded for INV-n at record revision N", summary, signer, PIN link, form, **Cancel**, **Sign conclusion**.

## Actions

| Action | Shown when | Who | Result |
|---|---|---|---|
| **Sign conclusion** | Always | Quality | "INV-n concluded."; returns to the investigation, which shows Conclusion |
| **Cancel** | Always | Quality | Nothing signed |

## Fields

| Field | Model field | Type / units | Required | Meaning and use |
|---|---|---|---|---|
| Outcome | `Investigation.outcome` | "Original result invalidated: assignable cause" or "Out-of-specification result confirmed" | Yes | Decision |
| Assignable laboratory cause | `Investigation.assignable_cause` | Text, max 4000 | For invalidation | "Required to invalidate the original result; cite the supporting evidence." |
| Conclusion | `Investigation.conclusion` | Text, max 2000 | Yes | Rationale |
| Signing username | — | Text | Yes | Must equal your own username |
| Signature PIN | `PINCredential` (checked, never stored) | Masked digits | Yes | Re-entered for every signature |
| Expected revision (hidden) | `Investigation.revision` | Integer | Yes | Revision when the page opened |

## Rules and hidden logic

- **Checked before the PIN form opens** (on opening and on submitting, with the same rules the signature uses): no PIN field is shown and no PIN checked when a conclusion is impossible. Redirects to the investigation with the first applicable warning: "Lot LOT-TEST-001 is no longer in quarantine."; "This investigation is already closed."; "You cannot conclude an investigation of your own work."; "Record the laboratory assessment first."; "The original result needs independent data review first."; "Authorized retests or resamples are still incomplete.". Outcome-specific rules (assignable cause, conforming reviewed retest) are checked on signing.
- **Preconditions**: investigation open ("This investigation is already closed."); not your own work, as defined above ("You cannot conclude an investigation of your own work."); assessment recorded ("Record the laboratory assessment first."); original Reviewed or Invalidated ("The original result needs independent data review first."); no authorized retest still open or awaiting review ("Authorized retests or resamples are still incomplete."); lot in quarantine.
- **Invalidation** also needs: a cause ("Invalidation requires a documented assignable cause."); no reviewed retest out of specification ("A retest or resample is also out of specification; the result cannot be invalidated."); at least one reviewed retest ("Invalidation requires a reviewed retest or resample result to report.").
- **Effect**: phase becomes Closed with time; a reviewed original becomes Invalidated on invalidation; lot revision rises by 1; `signed.concluded` and an immutable signature are stored. A confirmed result keeps blocking disposition.
- **Stale page, identity, session and PIN** messages as for other signings: "Record changed. Reload and review before signing."; "Enter your own signing username and PIN."; "Session expired. Sign in again before signing."; "Signature PIN was not accepted."; five failures lock for 15 minutes.

## Related pages

- Investigation record (return target).
- [Signature PIN](/signature-pin/)
