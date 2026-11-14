# Operations and recovery

This runbook covers the PostgreSQL 17 application and its Render deployment configuration. The procedures below are not themselves execution evidence; execute and record them in your own deployment. Keep executed checks, timestamps, operators, source revision, archive checksum and outcomes in restricted operational evidence. Do not place credentials or database archives in Git.

A synthetic restore rehearsal should cover: full migration of every registered app; an isolated PostgreSQL dump and transactional restore; exact table fingerprints; signature and audit binding checks; enabled trigger and function parity; sequence comparison; the Django check and the migration check. Compare any constraint definition that PostgreSQL rewrites on restore and confirm equivalent behavior. Confirm the source fingerprint is unchanged at the end.

Use a fixture that exercises every populated workflow you rely on: approved native specifications, analytical observations, QC and OOS records, laboratory resources and qualifications, stability records and issued PDFs. Test negative trigger mutations, point-in-time recovery, encrypted off-machine backups, runtime-role separation, identity recovery and file media restoration separately. A rehearsal that uses the trusted service channel does not exercise interactive username/PIN signing. A rehearsal alone does not establish RPO/RTO or production recovery acceptance.

## Bootstrap account access

In the intended instance's application shell, after migrations, create the individual bootstrap account and explicitly assign its laboratory role:

```sh
python manage.py createsuperuser --username admin
python manage.py assign_roles admin admin --actor admin --reason 'Bootstrap account administration'
```

Replace both occurrences of `admin` that identify the account if using another username; the role argument remains `admin`. For local development prefix commands with `uv run`. The assignment records the actor, prior/new roles and reason in the audit trail. `assign_roles` replaces the complete role set, so include every intended role when updating an existing account.

`createsuperuser` alone grants no laboratory role. The laboratory `admin` role permits reading every area (including audit export and CoA PDF) and account administration, not scientific mutation; those still require explicit roles and independent actors. It does not grant Django `is_staff` or superuser status. The signed-in **Account access** page explains missing roles and links authorized staff administrators to the existing read-only Django account view. Explicit admins also see **Users and roles**, the signed web management interface. A superuser without the explicit role sees bootstrap guidance but cannot use that interface. Users without a role should ask their organization's account administrator; the access page and sign-out remain available.

For an authorized synthetic demonstration in `DEBUG=true`, run `python manage.py seed_demo --actor admin --journey` only after the bootstrap sequence. The command accepts a superuser actor without the `admin` role but warns that the actor still lacks it; it never assigns roles to that actor. Seeding is deliberate and is not part of deployment or regulated production setup. `--publish-accounts` additionally writes the seeded non-administrator accounts, their shared password and their PIN into the sign-in announcement, signed by `demo_admin`, whose own credentials must differ (`DEMO_ADMIN_PASSWORD`, `DEMO_ADMIN_PIN`). Use it only on an instance meant to be open to anyone who can reach it. The published accounts can no longer change their own password or PIN; an administrator's forced password reset or PIN re-enrollment ends that for an account.

## Signed account administration

Accepted limitation: administrators are trusted to perform account administration. An admin who sets an initial or temporary password and requires PIN re-enrollment could act as that account. The application does not prevent this; laboratory SOPs and review of the audit trail (including `account.created`, `account.reset_password` and `account.reenroll_pin`) are the mitigations.

Enroll the administrator's own PIN at `/signature-pin/` by confirming the login password, then use **Users and roles**. Keep a second individually verified active admin for recovery. The service refuses self-granted additional roles and deactivation/removal of the last active admin; these checks also apply to the audited role command. Only the initial roleless-superuser bootstrap may self-assign exactly `admin` when no active admin exists.

| Action | Required operation and effect |
|---|---|
| Create account | Verify identity, enter the initial password privately, select roles, give a reason and sign. Share credentials through an approved private channel; the user must replace the password before workspace access |
| Assign/revoke roles | Review the complete replacement set, reason and sign. Admin alone grants no scientific authority |
| Deactivate/reactivate | Reason and sign; deactivation refuses login and both actions invalidate earlier sessions |
| Clear PIN lockout | Verify the individual's identity and investigate failed signing, then reason and sign; clears the signing lock without revealing/replacing the PIN |
| Require PIN re-enrollment | Reason and sign; removes the old hashed credential. The owner must enroll a new PIN with their current login password |
| Force password reset | Reason and sign; optionally enter a private temporary password. If left blank, the user signs in with their current password. Either way, replacement is mandatory before workspace access; the application sends no email |
| Change own password | Confirm the current password and provide a reason; no PIN is required for this recovery-capable operation. Only the current session is retained |
| Change sign-in announcement | Enter or edit the title and text, choose whether the sign-in page shows it, give a reason and sign. The text is public before sign-in and its earlier versions stay in the audit trail |

Every administrative web change signs the account revision with meaning `account_authorized` and records safe before/after values. A sign-in announcement change signs the announcement revision with meaning `announcement_authorized` and records the previous and new text. The account detail history shows this evidence; no password, PIN or credential hash is exposed. All account-management changes revoke existing target sessions on their next request; signatures additionally check revocation inside their transaction. Self-administration signs out the actor immediately. A stale page must be reloaded and reviewed before signing. Installing this release invalidates older sessions without account security epochs. Trusted `create_staff`/`assign_roles` operator commands remain audited but unsigned; restrict application-shell access and document its use under the recovery procedure.

## Responsibilities and recovery decisions

| Owner | Required decision or evidence |
|---|---|
| Deployment operator | Exact deployed commit/image, configuration, migration history, database identity and recovery access |
| Quality owner | Acceptable recovery point, records affected by a loss, reconciliation and release of recovered service |
| Security/account owner | Individual identity verification, access review, credential recovery, incident handling and session policy |
| Backup operator | Approved encrypted backup destination, access, retention, schedule and restore rehearsals |

The organization must set RPO/RTO and retention schedules before relying on this service. A local Docker volume is persistence, not an independent backup. PostgreSQL logical dumps cover one database, not cluster roles or external storage; retain controlled infrastructure/configuration records separately. `pg_dump -Fc` creates a consistent custom-format archive while normal activity continues. Use PostgreSQL 17 tools for this deployment. [PostgreSQL 17 pg_dump documentation](https://www.postgresql.org/docs/17/app-pgdump.html), accessed 2026-11-10.

## Local backup

Run from the project root against the intended Compose project. Confirm the server/database identity before exporting. These commands use the local Compose container, not a production URL, and make no source database changes.

```sh
docker compose exec -T db psql -U open_qual -d open_qual -X -v ON_ERROR_STOP=1 \
  -c 'SELECT current_database(), current_user, version();'
umask 077
mkdir -p backups
oq_backup_stamp=$(date -u +%Y%m%dT%H%M%SZ)
oq_backup_file="./backups/fresh-coa-lims-${oq_backup_stamp}.dump"
docker compose exec -T db pg_dump -U open_qual -d open_qual \
  --format=custom --no-owner --no-acl > "$oq_backup_file"
```

Stop if the dump exits nonzero; a partial output file is not a backup. Review stderr, then inspect the archive and record a checksum:

```sh
docker compose exec -T db pg_restore --list < "$oq_backup_file" \
  > "${oq_backup_file}.contents"
shasum -a 256 "$oq_backup_file" > "${oq_backup_file}.sha256"
```

The local archive contains account records, PIN/password hashes and sessions, even for a synthetic instance. Keep it restricted and transfer it to the approved encrypted backup destination; an ignored local directory is not encryption or off-machine protection. Keep a source revision/configuration manifest alongside the encrypted artifact, without secret values. The `--no-owner --no-acl` portability choice means role ownership/grants must be re-established explicitly at restoration.

## Restore rehearsal into a new local database

Use an archive created by a trusted operator. Restoration executes database code from the archive, so review provenance and do not restore untrusted uploads. Restore into a **new, isolated database**; do not point these commands at `open_qual`, an active test database or any deployed database. Full schema/data restoration reinstates constraints and triggers; do not pre-run Django migrations into the empty target. `--single-transaction` and `--exit-on-error` prevent accepting a partial restore. [PostgreSQL 17 pg_restore documentation](https://www.postgresql.org/docs/17/app-pgrestore.html), accessed 2026-11-10.

In the same shell as the backup example, or after explicitly setting `oq_backup_file` to the selected archive:

```sh
oq_restore_db="oq_restore_$(date -u +%Y%m%d_%H%M%S)"
docker compose exec -T db createdb -U open_qual --template=template0 "$oq_restore_db"
```

Continue only if creation succeeds; an existing target name is a stop condition. Do not overwrite it or add `--clean`/`--create` flags to the restore.

```sh
docker compose exec -T db pg_restore -U open_qual --dbname="$oq_restore_db" \
  --no-owner --no-acl --single-transaction --exit-on-error < "$oq_backup_file"
```

Retain the target for inspection. No cleanup/drop operation is included here. Verify identity and migration state using the matching source revision before testing a newer version:

```sh
docker compose exec -T db psql -U open_qual -d "$oq_restore_db" -X -v ON_ERROR_STOP=1 \
  -c 'SELECT current_database(), current_user;'
DEBUG=true DATABASE_URL="postgresql://open_qual:open_qual@127.0.0.1:55433/${oq_restore_db}" \
  uv run python manage.py check
DEBUG=true DATABASE_URL="postgresql://open_qual:open_qual@127.0.0.1:55433/${oq_restore_db}" \
  uv run python manage.py migrate --check
```

`migrate --check` does not apply migrations. Rehearse any new migration only after the restored baseline passes integrity checks, with no application connected to this target. Do not reuse restored sessions or expose the rehearsal server publicly. Do not run scientific test mutations against restored real records; use an independently created synthetic validation database for destructive/negative tests.

## Integrity acceptance

| Check | Required result |
|---|---|
| Archive and provenance | Checksum matches stored manifest; source database, dump time and deployed revision are known |
| Schema | Expected migrations applied; restored foreign keys, uniqueness constraints, functions and enabled triggers match the release migrations |
| Evidence | Counts and known record IDs/revisions match the backup manifest/snapshot; any intentionally older recovery point has a documented reconciliation |
| Signature binding | Stored content hashes recompute; signer, meaning, time, record type/ID/revision and linked audit event remain present |
| Histories | Audit reviews retain selected events; approved rules, samples/results and signed disposition evidence remain retrievable |
| Application | Matching code passes check/readiness, authorized reads and stored export retrieval; access controls still apply |
| Operations | Recovery time and lost-work interval measured against approved RTO/RPO; quality owner records acceptance before traffic switch |

Counts captured separately on a busy source may differ legitimately from a dump snapshot. For exact comparisons, coordinate a brief write pause or collect the baseline from the restored archive itself and compare against independent known evidence. A matching hash demonstrates consistency with stored content, not resistance to an administrator rewriting both.

List actual user triggers with this read-only query and compare definitions with **all migrations in the deployed revision**, including later domain apps:

```sh
docker compose exec -T db psql -U open_qual -d "$oq_restore_db" -X -v ON_ERROR_STOP=1 <<'SQL'
SELECT n.nspname, c.relname, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid)
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT t.tgisinternal AND n.nspname = 'public'
ORDER BY c.relname, t.tgname;
SQL
```

The foundation includes audit/signature/review history guards, approved-rule guards and lot/sample/result evidence guards. Merely counting triggers is insufficient; inspect their definitions and enabled status. DB owners can disable them, so keep runtime privileges distinct from migration/maintenance privileges before production use.

Recompute all signature hashes without displaying scientific payloads or credential hashes:

```sh
DEBUG=true DATABASE_URL="postgresql://open_qual:open_qual@127.0.0.1:55433/${oq_restore_db}" \
  uv run python manage.py shell <<'PY'
import hashlib
import json
from core.models import ElectronicSignature

checked = 0
for signature in ElectronicSignature.objects.select_related("audit_event").iterator():
    encoded = json.dumps(signature.content, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == signature.content_hash, signature.pk
    event = signature.audit_event
    assert event.actor_id == signature.signer_id, signature.pk
    assert event.object_type == signature.object_type, signature.pk
    assert event.object_id == signature.object_id, signature.pk
    assert event.after == signature.content, signature.pk
    assert signature.content["revision"] == signature.revision, signature.pk
    checked += 1
print(f"Verified {checked} stored signature snapshots and audit links.")
PY
```

Zero signatures is meaningful only for a genuinely unsigned source database. Check signed fixture/record coverage in the manifest. Historical signatures bind historical snapshots; their revision need not equal a record's latest revision. The script is a targeted integrity check, not a complete restore acceptance suite.

## Render backup and recovery

The Blueprint names `fresh-coa-lims` and `fresh-coa-lims-db` (database name/user `open_qual`), with database external access closed. Do not change network exposure just to perform a routine export. In the database's **Recovery** page, use **Create export**, then download and protect the archive. Render exports are directory-format `.dir.tar.gz`, not the custom-format local dump above: extract in an isolated restricted directory and give `pg_restore` the extracted directory containing `toc.dat`. Use the same fresh-target and no-overwrite safeguards.

Paid Render databases provide PITR into a new database instance, allowing validation before switching the web service. Availability depends on the workspace's current recovery window; verify the available point in the dashboard. Managed retention is not the organization's records-retention policy, so retain approved encrypted exports independently. New recovery resources and access changes follow the deployment owner's authorization. [Render recovery and backup procedure](https://render.com/docs/postgresql-backups), accessed 2026-11-10.

For an incident, preserve the original service/database, record the requested recovery time, and restore into a separate instance. Keep it private. Run the integrity acceptance against matching code, reconcile transactions after the recovery point, and obtain quality-owner acceptance. Switch `DATABASE_URL` only as a coordinated cutover with writers stopped; prevent old and recovered databases from both accepting new scientific records. Keep the previous instance until acceptance and retention decisions are recorded.

## Demonstration deployment from `develop`

The project's synthetic demonstration follows `develop`: the Blueprint sets `branch: develop` and `autoDeployTrigger: checksPass`, so Render deploys a commit only after all of its GitHub checks succeed, and does not deploy a commit with a failed check or with none. Under the workspace's **Wait** overlapping-deploy policy, a deploy triggered while another is running waits for it and only the newest waiting commit is deployed; confirm the policy in the workspace settings. A failed build or pre-deploy leaves the previous version serving. Put `[skip render]` in a commit message to keep that commit from deploying.

Each deploy runs the pre-deploy migration against the demonstration's persistent database. A migration merged to `develop` has therefore been applied; correct it with a new migration, never by editing it. This arrangement suits synthetic data only. A deployment holding controlled records keeps auto-deploy off, tracks a release branch and follows the manual procedure below.

## Demonstration reset

A public demonstration whose accounts are published can return to the seed's state on a schedule. This is for synthetic data only. `reset_demo` empties every application table, including accounts, sessions, signatures, audit history and issued reports, and restarts identifiers. The database triggers that keep history rows from being updated or deleted do not apply to this whole-table erase. That is deliberate, and it is why the command is fenced.

```sh
ALLOW_DEMO_RESET=true python manage.py reset_demo --publish-accounts
```

It asks for confirmation unless `--noinput` is given, never asks for credentials, and refuses before erasing anything unless all of these hold:

| Check | Why |
|---|---|
| `ALLOW_DEMO_RESET=true` in the job's environment | The deployment declares itself a demonstration. `DEBUG` alone is not enough, and a laboratory's deployment never sets it |
| `DEMO_PASSWORD`, `DEMO_PIN`, `DEMO_ADMIN_PASSWORD` and `DEMO_ADMIN_PIN` are set, both PINs have 8–32 digits, and `demo_admin`'s pair differs from the published pair | After a reset `demo_admin` is the only administrator, so nothing published may open it |
| The database is empty, or holds the `demo_admin` account that `seed_demo` created | A laboratory's database is never erased |
| No migration is pending and none is unknown to the release | A job from another release than the web service would seed the wrong schema |
| `--journey` is given only with `DEBUG=true` | The journey's result uses the development-only entry path |

A run has two parts:

1. One transaction erases the tables, creates `demo_admin` (the admin role only, no staff or superuser status) with its private password and PIN, and runs `seed_demo` for the other accounts and the draft rules and catalog/sampling profiles. If any of it fails, the transaction rolls back and nothing changes. Requests that arrive meanwhile wait, then see the fresh demonstration; everyone is signed out.
2. The signed steps follow in transactions of their own, because signing never runs inside an enclosing transaction. With `--publish-accounts` the listed accounts' credentials are locked and the announcement is published, signed by `demo_admin`. With `--journey` the chemical rule is approved and the result awaiting review is created. If a signed step fails, the command fails and says so: the demonstration is seeded but lacks that step until the next run.

`ALLOW_DEMO_RESET=true` also lets `seed_demo` run without `DEBUG`, without `--journey`. `DEMO_RESET_NOTE`, if set, ends the announcement, for example with the time of the reset.

On Render the schedule is `render.demo.yaml`, a Blueprint separate from `render.yaml`. In the workspace that already runs the demonstration from `render.yaml`:

1. Create a new Blueprint from the same repository and branch with **Blueprint Path** `render.demo.yaml`. It adds one paid cron job, `fresh-coa-lims-demo-reset`, and refers to the existing web service and database by name. Render asks once for `DEMO_PASSWORD` and `DEMO_PIN`, which will be public, and `DEMO_ADMIN_PASSWORD` and `DEMO_ADMIN_PIN`, which must differ and stay private.
2. Use **Trigger Run** on the job to reset straight away, or wait for the schedule (every day at 08:00 UTC). Change the time in the file's `schedule` and `DEMO_RESET_NOTE` together.

The first run erases whatever the demonstration holds, including accounts created by hand; afterwards administer it as `demo_admin`. The job follows `develop` with the same trigger as the web service. While a release with a migration is being deployed, a run may refuse until the web service has migrated; the next run succeeds.

Render bills a cron job by the second of running time, with a minimum monthly charge per cron job service, and schedules use UTC. [Render cron jobs](https://render.com/docs/cronjobs), accessed 2026-11-12. `render blueprints validate render.demo.yaml` (CLI 2.36.0) accepted the file against the demonstration's workspace on that date, planning one new service; it creates nothing.

## Manual deployment and migrations

The repository is <https://github.com/openbga/fresh-coa-lims>. Keep `SOURCE_CODE_URL` pointing at the source of the deployed version.

1. Select the reviewed commit whose checks all passed. Record its identifier and a verified backup/recovery point. Inspect pending migrations and compatibility with the currently running version.
2. Verify that the OpenBGA Fresh CoA LIMS web service targets its own database and that auto-deploy remains off. In Render's Manual Deploy menu choose the exact reviewed commit. Avoid “latest” when it may have advanced beyond the tested revision.
3. The configured pre-deploy command is `python manage.py migrate --noinput`. Allow this single serialized migration owner to run; do not launch a second migration from a shell. A failed pre-deploy requires inspection, not bypassing the migration gate.
4. Inspect deploy/migration logs, then verify `/health/`, `/ready/`, login and authorized read/signing flows using controlled synthetic records. Record outcomes and operator/time.
5. If code is rolled back, first verify compatibility with the already-migrated schema. Code rollback does not reverse migrations. For incompatible/destructive changes, use the separately rehearsed recovery plan and reconcile lost work.

Render supports automatic deployment after CI checks, manual deployment of a selected commit and a pre-deploy stage. Current service configuration remains the source of truth. [Render deployment documentation](https://render.com/docs/deploys), accessed 2026-11-12.

For an exceptional operator-run migration, stop competing deployment attempts first, confirm the shell contains the intended application revision and database, and run `python manage.py showmigrations --plan`, then the reviewed `python manage.py migrate --noinput`, followed by `python manage.py migrate --check` and `python manage.py check`. Never run `makemigrations` on a deployed instance or edit historical migrations to resolve a failure. Do not run seed/reset commands during routine deployment.

## Bench checks at result entry

Before a native observation or batch QC result is recorded or corrected, the analyst needs independently approved qualification evidence whose activity matches the method code (case-insensitive). The validity dates must cover the current deployment-local date, approval must already have occurred, and revocation must not have taken effect. A role assignment alone does not satisfy this check. Preserve the referenced training/suitability evidence under the organization's controlled procedure.

The entry also names the instruments and the reagent or standard lots used. Each selected instrument must be in service with an independently accepted calibration that has not expired and, where the equipment requires it, current qualification evidence. Each selected lot and its source lots must be released and unexpired. A method version can require at least one instrument, at least one lot, or both; set this when the version is created, because it cannot be changed on an existing draft. Register equipment, record and accept calibrations and release lots before testing starts, or entries for such methods are refused.

The configured `ANALYTICAL_BENCH` is `config.integrations.LaboratoryBench`; removing the setting holds every observation and batch QC entry. A successful entry freezes the user, activity, qualification, instruments and lots on the result and its audit event, and adds one resource-use row per instrument or lot. A refused entry stores nothing; the refusal is recorded as the audit event `resource.use_blocked`. Correction rechecks the correcting analyst and the resources selected for the correction. Existing evidence is preserved after a later expiry, revocation or failed calibration.

After a failed calibration the equipment is out of service, and its page lists the tests and QC batches that used it since the last accepted passing calibration. The signed return to service records that this list was assessed; deciding what to do about each affected result remains a quality decision outside the software.

The software checks what the analyst selects. It does not know which instrument or lot a method needs, and results recorded before this check existed carry no instrument or lot. Validate these boundaries and failure cases when approving the deployed workflow.

## Suppliers and receipt details

A lot is received with its receipt details, so a lot from a supplier needs that supplier on the register first. A quality user adds suppliers under **Suppliers**; a supplier's identity cannot be edited or removed afterwards, so add a new entry when a name or site changes. The register does not record qualification, and the software does not check a supplier's status at receipt or reduce testing because of it: keep supplier approval under the organization's own procedure.

Receipt details are corrected only while the lot is in quarantine, by a new record that keeps the one it replaces. A discrepancy recorded on receipt does not hold the lot; place a hold when the lot must not be dispositioned until it is resolved. Lots received before this release have no receipt details. An analyst can record them from the delivery documents while the lot is in quarantine; a lot released earlier stays without them.

The demonstration seed adds two synthetic suppliers. On a demonstration with a scheduled reset they appear at the next reset after this release is deployed; until then a quality account adds one.

## Calculated results

A calculation is approved with the method version: the formula, its named inputs with units, the unit of the result and its decimals. The quality owner who approves the version is approving the formula; verify it against the controlled procedure with worked examples before approval, and again in intended-use validation. The software evaluates the formula exactly as written, carries 50 significant digits and rounds the result half-up to the approved decimals. It does not convert units, apply significant-figure rules or round intermediate values. Changing a formula means a new method version; tests already assigned keep the formula they froze.

## Raw-data files

Raw-data files attached to tests are stored in the PostgreSQL database, so they are included in database backups and count toward database size. `RAW_DATA_MAX_BYTES` sets the largest accepted file (default 10 MiB, at most 50 MiB); a test holds at most 20 files. Files are kept exactly as received and are never opened by the software, which also means they are not scanned for malware: handle downloaded files under the organization's own controls. A file cannot be removed once attached. `RAW_DATA_TOTAL_MAX_BYTES` sets an optional ceiling on all raw-data files together (0, the default, sets none); once it is reached further files are refused. On a public demonstration set a small file limit and a ceiling, as the demonstration blueprint does. A file above the limit is refused in the browser before it is sent. The server refuses an upload that declares more than the file limit plus 1 MiB with status 413 before reading its body, and closes the connection; a file that is over the limit by less is stopped while it arrives. This relies on the server closing the connection after an unread request, as the Gunicorn command in the image does; a different server or a proxy that buffers uploads may still receive the whole request.

## Accounts, sessions and signing

| Operation | Procedure and boundary |
|---|---|
| Provision | Verify individual identity under the organization's SOP. Use signed **Users and roles**, or audited `create_staff` in the controlled operator shell, with a named administrator and reason; passwords are entered privately. Avoid shared accounts and shared PINs |
| Roles | Use signed **Assign roles** or the audited `assign_roles` operator command; both replace the whole role set. Zero roles revokes laboratory authority. Superuser/admin status is not scientific review authority |
| PIN enrollment/replacement | Owner confirms current login password at `/signature-pin/`; 8–32 digits, Django hash storage and an attributed event. Never retrieve a PIN or reset by editing credential rows |
| Failed signing | Five failed PIN attempts cause a 15-minute signing lock. Review denied-signature events for misuse. Investigate before repeated recovery; do not clear counters through SQL |
| Failed sign-in | Password sign-in, PIN enrollment and own password change share one persistent failure counter per account. After `LOGIN_FAILURE_LIMIT` consecutive failures (default 5) password authentication is refused for `LOGIN_LOCK_SECONDS` (default 900), even with the correct password; the lock expires on its own and there is no administrator unlock. Anyone who knows a username can trigger a lock, so add per-address rate limiting at the reverse proxy and review repeated locks |
| Transport and browser policy | With `DEBUG` off: HTTPS redirect, secure cookies and HSTS for one year (`SECURE_HSTS_SECONDS`; lower it while first verifying HTTPS). `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` are opt-in because they affect other hosts. HTML responses carry a same-origin Content-Security-Policy; update it before adding any external script, style or font. The application trusts `X-Forwarded-Proto`, so serve only behind a proxy that overwrites it and never expose the application port directly |
| Error reports | Credential fields (`password*`, `pin`) are masked in Django error reports. Configure any additional error tracker not to capture request bodies |
| Signing context | Review displayed identity, record revision, meaning and reason. Each HTTP signature requires username and PIN re-entry matching the authenticated individual; the server rechecks state/authority and commits transition/signature/audit atomically |
| Sign-in activity | Every sign-in, failed attempt and sign-out writes one `openbga.signin` line to standard output with the username and the `Rndr-Id` request ID (`-` when absent). On Render, search that ID in the HTTP request log (Pro workspaces and higher) to find the client IP. Lines are kept only for the log platform's retention; stream logs to a controlled destination for longer history. Treat usernames and IP addresses as personal data and set a retention period |
| Session expiry | `SESSION_IDLE_SECONDS=900` (15 minutes) and `SESSION_ABSOLUTE_SECONDS=28800` (8 hours) are the defaults; server expiry requires login again. Existing sessions without login clocks are invalidated; confirm the deployed values |
| Suspicious access/revocation | Revoke laboratory roles promptly through the audited service and follow the approved account/session incident process. Account-management changes revoke previous sessions on their next request; deactivate when login and all authenticated read access must be refused |
| Recovery | Identity owner documents verification and authorizes recovery without asking the signer to disclose a secret. Test the actual recovery/session invalidation behavior before production use |

Username-plus-PIN entry and session limits are software controls, not a declaration of Part 11 compliance or MFA. Identity uniqueness, verified identity, controlled sessions, credential safeguards, intended-use validation and applicable certification/procedures remain the organization's responsibility; see [REG-E09–11 in the regulatory matrix](regulations.md). HTTP signing uses the `signature_username` field plus PIN and records authentication context, including login time, without storing a raw session ID. Trusted programmatic service calls are marked as PIN-only service signatures; do not present them as the validated interactive flow. Check the deployed form, middleware and regression tests when changing these controls. Protect HTTPS, trusted origins, secure cookies, time synchronization and operational logs. Never log submitted passwords/PINs or copy session/credential data into incident reports.
