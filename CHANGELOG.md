# Changelog

All notable changes to OpenBGA Fresh CoA LIMS are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project is pre-1.0 and does not yet promise a stable interface.

## [Unreleased]

### Changed

- Whoever recorded or corrected a lot's receipt details can no longer sign that lot's QC disposition. The **Number** field of the new-lot form is now **Lot number**.
- `ANALYTICAL_BENCH` replaces `ANALYTICAL_ELIGIBILITY_CHECK`. A deployment that overrides the old setting must name a bench class instead; without one, results are held.
- Adopted the OpenBGA Fresh CoA LIMS name and certificate-and-leaf mark across the application, presentation and newly issued certificates.
- Moved the source repository and presentation to the `fresh-coa-lims` slug, with the hosted demo at `fresh-coa-lims.onrender.com`.
- The Render Blueprint and hosted demo now deploy `develop` automatically once CI checks pass; controlled deployments keep automatic deployment off.

### Added

- Receipt details and a supplier register: a lot is received together with where it came from (a supplier from the register, or made on site), the supplier's and manufacturer's lot numbers, the delivery document, the date, the quantity, the containers and what the examination on receipt found. Details are never edited; a correction adds a linked record with its reason while the lot is in quarantine. Quality keeps the register, which records identity only and does not qualify a supplier. The lot list shows the supplier and searches supplier and manufacturer lot numbers. Lots received earlier have no receipt details until an analyst records them.
- Calculated results: a method version can define one formula over named inputs with units, approved and frozen with the version. The analyst enters the inputs, the system calculates the value, and the result keeps the inputs, the formula and the method version. Submission and review calculate again.
- Equipment and reagent checks at result entry: recording or correcting a result or a batch QC check names the instruments and the reagent or standard lots used. An entry is refused when an instrument is out of service or out of calibration, a lot is not released or expired, or the analyst has no current qualification for the method, which now applies to batch QC as well. A method version can require an instrument, a lot or both. After a failed calibration the equipment page lists the tests and QC batches that used the equipment.
- Raw-data files: a file can be attached to a test, is stored with its SHA-256 checksum, never changes and is returned unchanged on download. `RAW_DATA_MAX_BYTES` sets the largest accepted file and `RAW_DATA_TOTAL_MAX_BYTES` an optional ceiling for all files together. A larger file is refused in the browser before it is sent, and the server answers an oversized upload with status 413 without reading it.
- More result types in native testing: counts, qualitative results (conforms or does not conform, absent or present) recorded with what was observed, results reported as less than a value kept as recorded, and specification limits that exclude their boundary. Certificates show the acceptance text and the result as recorded. A qualitative specification line now needs an expected outcome; lines approved without one are held until a new version states it.
- Sign-in announcement: one notice on the sign-in page that administrators write, publish and withdraw with a signed, audited change. The development seed can publish its non-administrator demo accounts there (`seed_demo --publish-accounts`).

Initial public source release (project version 0.1.0), licensed AGPL-3.0-only. Implemented areas:

- Approved methods and specifications, sampling plans and sampling assignments, with independently approved revisions and frozen applicability snapshots on lot assignments.
- Lot and sample records, numeric observations with replicates, and method QC batches.
- Out-of-specification investigations with controlled assessment, retest and resample authorization, and conclusion.
- Independent signed review and QC disposition that checks assigned requirements, review state, investigations, independence and active holds.
- Immutable PDF certificates of analysis with signed issuance, amendments, stored bytes, snapshots and checksums.
- Laboratory resource records and method-specific analyst qualification authorization.
- Stability protocols and scheduled pulls, reserves, retention obligations and holds.
- Shared rule revisions, PIN signatures (hashed, rate-limited, re-entered for every signing) and attributed audit history.
- Named user accounts with explicit roles, signed account administration, session limits and a read-only Django admin.
- In-app page documentation for every staff page, and a static presentation website published with GitHub Pages.
- Sign-in throttling, a same-origin Content-Security-Policy and credential masking in error reports.
- Container image, CI workflow, a Docker Compose profile for local evaluation and a Render Blueprint for manual deployment.

### Limits

- Greater-than results and batch QC checks other than directly entered numeric values with inclusive limits are not supported. A method states that an instrument or a lot is required, not which one.
- Stability testing of released lots uses external evidence, because released lot records are immutable.
- Manufacturer batch release is a separate decision and is not performed by the software.
- Multi-factor authentication, identity proofing, PIN recovery policy, backup and restore acceptance, retention and intended-use validation remain the responsibility of each deployment.
- Segment presets are synthetic drafts, not complete policies.
- No regulatory compliance, validation or certification is claimed. Use synthetic data only.
