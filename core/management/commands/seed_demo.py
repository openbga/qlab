"""Synthetic demonstration fixtures, created through the application's public services.

For development (DEBUG) and for a deployment that declares itself a demonstration with
ALLOW_DEMO_RESET=true. Never for a database where a laboratory keeps its records.
"""

import os
import shlex
from decimal import Decimal
from getpass import getpass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.administration import lock_credentials
from accounts.announcements import ROLE as ANNOUNCEMENT_ROLE
from accounts.announcements import change_announcement, current_announcement
from accounts.models import LoginAnnouncement
from accounts.services import ROLES, provision_account
from core.management.commands.seed_rules import SEED_REASON
from core.models import AuditEvent, PINCredential, RuleSet
from core.services import approve_rule, set_pin
from quality.models import Lot, Result, Sample
from quality.services import add_sample, receive_lot, record_result
from suppliers.models import Supplier
from suppliers.services import create_supplier

MARKER = "Synthetic seed_demo account; development only."
LOT_NUMBER = "SYNTHETIC-DEMO-001"
SAMPLE_REFERENCE = "SYNTHETIC-DEMO-S001"
DEMO_ROLES = {role: role for role in ROLES} | {"config_author": "quality"}
# Synthetic suppliers for the register, so a demonstration lot can name where it came from.
SUPPLIERS = (
    ("sup-syn-001", "Synthetic Ingredients Supply", "Sampletown, Exampleland"),
    ("sup-syn-002", "Example Packaging Works", "Testville, Exampleland"),
)
SUPPLIER_REASON = "Synthetic demonstration supplier; not a qualified supplier."
SEGMENTS = ("pharma", "supplement", "food", "chemical", "device")
ANNOUNCEMENT_TITLE = "Demonstration accounts"
ANNOUNCEMENT_REASON = "Synthetic demo accounts published by seed_demo --publish-accounts."
LOCK_REASON = (
    "Published in the sign-in announcement by seed_demo --publish-accounts; anyone can sign in "
    "to this account."
)
JOURNEY_NEEDS_DEBUG = (
    "--journey records a result through the development-only entry path and needs DEBUG=true. "
    "Nothing was changed."
)
# What each published account is for, in the order of the work.
PUBLISHED_USES = {
    "demo_analyst": "Receive lots and samples, record observations and batch QC",
    "demo_reviewer": "Review records and results",
    "demo_quality": "Approve configuration and make QC disposition decisions",
    "demo_config_author": "Draft configuration for `demo_quality` to approve",
    "demo_auditor": "Read records and the audit history",
}


def demo_deployment():
    """Whether this deployment declares itself a demonstration that may be seeded and reset.

    ALLOW_DEMO_RESET=true belongs on a demonstration's reset job only, never where a laboratory
    keeps its records.
    """
    return os.environ.get("ALLOW_DEMO_RESET", "").lower() == "true"


def reset_note():
    """The announcement's last sentence, for a deployment with a scheduled reset_demo."""
    return " ".join(os.environ.get("DEMO_RESET_NOTE", "").split())


def _secret(name, prompt):
    return os.environ.get(name) or getpass(prompt)


def _pin(name, prompt):
    value = _secret(name, prompt)
    if not value.isascii() or not value.isdigit() or not 8 <= len(value) <= 32:
        raise CommandError(f"{name} must contain 8–32 ASCII digits.")
    return value


def _announcement_text(accounts, password, pin, note=""):
    order = list(PUBLISHED_USES)
    accounts = sorted(
        accounts, key=lambda row: (order.index(row[0]) if row[0] in order else len(order), row[0])
    )
    rows = "\n".join(
        f"| `{username}` | {roles} | {PUBLISHED_USES.get(username, '—')} |"
        for username, roles in accounts
    )
    return (
        "Public demonstration with synthetic data. Sign in as:\n\n"
        f"| Username | Role | Use it to |\n|---|---|---|\n{rows}\n\n"
        f"Password for each\n\n```\n{password}\n```\n\n"
        f"Signature PIN for each, asked when signing a record\n\n```\n{pin}\n```\n\n"
        "A record cannot be reviewed or approved by the account that created it; "
        "use another account for that step.\n\n"
        "Do not enter real data. Anyone can use these accounts." + (f" {note}" if note else "")
    )


def check_publishable(password, pin, note):
    """Refuse, before anything is written, what the announcement cannot show."""
    # The announcement shows the password on a line of its own inside a code fence.
    if (
        password != password.strip()
        or "\n" in password
        or "\r" in password
        or password.startswith("```")
    ):
        raise CommandError("DEMO_PASSWORD cannot be shown exactly in the announcement.")
    rows = [(username, "Reviewer") for username in PUBLISHED_USES]
    if len(_announcement_text(rows, password, pin, note)) > LoginAnnouncement.BODY_LIMIT:
        raise CommandError("The announcement would be too long. Shorten DEMO_RESET_NOTE.")


class Command(BaseCommand):
    help = (
        "Seed synthetic demo accounts and draft presets (DEBUG, or a demonstration deployment "
        "with ALLOW_DEMO_RESET=true); never reset credentials."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--actor", required=True, help="Existing account administrator username"
        )
        parser.add_argument(
            "--journey",
            action="store_true",
            help="Approve the synthetic chemical preset and create a result awaiting review",
        )
        parser.add_argument(
            "--publish-accounts",
            action="store_true",
            help="Show the demo accounts that cannot change the sign-in announcement, with "
            "their password and signature PIN, in that announcement",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not demo_deployment():
            raise CommandError(
                "seed_demo is available only with DEBUG=true, or on a demonstration deployment "
                "that sets ALLOW_DEMO_RESET=true."
            )
        if options["journey"] and not settings.DEBUG:
            raise CommandError(JOURNEY_NEEDS_DEBUG)
        users = get_user_model()
        try:
            actor = users.objects.get(username=options["actor"], is_active=True)
        except users.DoesNotExist as exc:
            raise CommandError("An existing active account administrator is required.") from exc
        has_admin_role = actor.groups.filter(name="admin").exists()
        if not actor.is_superuser and not has_admin_role:
            raise CommandError("The actor must be an account administrator.")
        if not has_admin_role:
            bootstrap = shlex.join(
                [
                    "python",
                    "manage.py",
                    "assign_roles",
                    actor.username,
                    "admin",
                    "--actor",
                    actor.username,
                    "--reason",
                    "Bootstrap account administration",
                ]
            )
            self.stderr.write(
                self.style.WARNING(
                    "The seed actor has no admin laboratory role. Superuser status permits "
                    "this command but grants no laboratory role; seeding does not assign one "
                    f"to the actor. For initial bootstrap, run: {bootstrap}\n"
                    "assign_roles replaces the complete role set; include every intended role."
                )
            )
        existing = {}
        # Preflight the entire namespace before creating anything. An audit marker, rather than
        # a username prefix alone, establishes that this command created an account.
        for role in sorted(DEMO_ROLES):
            username = f"demo_{role}"
            user = users.objects.filter(username=username).first()
            if user:
                if not AuditEvent.objects.filter(
                    object_type="accounts.user",
                    object_id=str(user.pk),
                    action="account.created",
                    reason=MARKER,
                ).exists():
                    raise CommandError(f"Refusing non-demo account collision: {username}.")
                existing[role] = user
        known_authors = {
            user.pk for key, user in existing.items() if key in {"admin", "config_author"}
        }
        for rule in RuleSet.objects.filter(code__in=SEGMENTS):
            seeded = AuditEvent.objects.filter(
                object_type="core.ruleset",
                object_id=str(rule.pk),
                action="rule.created",
                actor_id=rule.author_id,
                reason=SEED_REASON,
            ).exists()
            if rule.author_id not in known_authors or not seeded:
                raise CommandError(f"Refusing non-demo rule-set collision: {rule.code}.")
        for supplier in Supplier.objects.filter(code__in=[code for code, _, _ in SUPPLIERS]):
            seeded = AuditEvent.objects.filter(
                object_type="suppliers.supplier",
                object_id=str(supplier.pk),
                action="supplier.created",
                actor_id=supplier.created_by_id,
                reason=SUPPLIER_REASON,
            ).exists()
            if supplier.created_by_id not in known_authors or not seeded:
                raise CommandError(f"Refusing non-demo supplier collision: {supplier.code}.")
        analyst = existing.get("analyst")
        lot = Lot.objects.filter(number=LOT_NUMBER).first()
        if lot and (analyst is None or lot.created_by_id != analyst.pk):
            raise CommandError("Refusing non-demo lot collision.")
        sample = Sample.objects.filter(reference=SAMPLE_REFERENCE).first()
        if sample and (lot is None or sample.lot_id != lot.pk):
            raise CommandError("Refusing non-demo sample collision.")
        publish = options["publish_accounts"]
        if publish and current_announcement().body:
            # An administrator's text is never replaced, and no credential is asked for.
            self.stdout.write("The sign-in announcement already has text; it was left unchanged.")
            publish = False
        password = pin = None
        if publish or len(existing) != len(DEMO_ROLES):
            password = _secret("DEMO_PASSWORD", "Synthetic demo login password: ")
            pin = _pin("DEMO_PIN", "Synthetic demo signature PIN: ")
        # demo_admin shares the demo credentials unless its own are supplied. Publishing requires
        # its own: published credentials must not open an account that can change the announcement.
        admin_password = os.environ.get("DEMO_ADMIN_PASSWORD") or password
        admin_pin = os.environ.get("DEMO_ADMIN_PIN") or pin
        if publish:
            if "admin" not in existing:
                admin_password = _secret(
                    "DEMO_ADMIN_PASSWORD", "Synthetic demo administrator login password: "
                )
            admin_pin = _pin("DEMO_ADMIN_PIN", "Synthetic demo administrator signature PIN: ")
            if admin_pin == pin or ("admin" not in existing and admin_password == password):
                raise CommandError(
                    "demo_admin needs a password and PIN different from the published accounts."
                )
            check_publishable(password, pin, reset_note())
        try:
            with transaction.atomic():
                for role in sorted(DEMO_ROLES):
                    if role not in existing:
                        secret, code = (
                            (admin_password, admin_pin) if role == "admin" else (password, pin)
                        )
                        user = provision_account(
                            actor=actor,
                            username=f"demo_{role}",
                            password=secret,
                            first_name="Synthetic",
                            last_name=role.title(),
                            roles=[DEMO_ROLES[role]],
                            reason=MARKER,
                        )
                        set_pin(actor=user, pin=code, password=secret)
                        existing[role] = user
                call_command(
                    "seed_rules", actor=existing["config_author"].username, stdout=self.stdout
                )
                # Catalog authoring is scientific quality authority, not account administration.
                # This command creates drafts only; their author cannot independently approve them.
                call_command(
                    "seed_qc_profiles", actor=existing["config_author"].username, stdout=self.stdout
                )
                # The register names suppliers; it does not qualify them.
                for code, name, location in SUPPLIERS:
                    if not Supplier.objects.filter(code=code).exists():
                        create_supplier(
                            actor=existing["config_author"],
                            code=code,
                            name=name,
                            location=location,
                            reason=SUPPLIER_REASON,
                        )
            if options["journey"]:
                self.seed_journey(existing, pin)
            if publish:
                self.publish_accounts(existing, password, pin, admin_pin)
        except (PermissionDenied, ValidationError) as exc:
            # Domain validation messages never include supplied credentials.
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Synthetic demo ready. Existing credentials and records were preserved. "
                "Accounts: " + ", ".join(f"demo_{role}" for role in sorted(DEMO_ROLES))
            )
        )

    def publish_accounts(self, people, password, pin, admin_pin):
        """Announce the demo accounts that cannot change the announcement, signed by demo_admin.

        Nothing is published unless every listed account accepts the credentials shown and no
        administrator (the admin role, which changes the announcement, or a superuser, who can
        take that role) accepts either of them. The listed accounts can no longer change their
        own password or PIN.
        """
        users = get_user_model()
        managers = list(
            users.objects.filter(is_active=True)
            .filter(Q(groups__name=ANNOUNCEMENT_ROLE) | Q(is_superuser=True))
            .distinct()
        )
        listed = list(
            users.objects.filter(pk__in=[user.pk for user in people.values()], is_active=True)
            .exclude(pk__in=[user.pk for user in managers])
            .order_by("username")
        )
        if not listed:
            raise CommandError("Every demo account is an administrator; none can be published.")

        def accepts(user):
            credential = PINCredential.objects.filter(user=user).first()
            return (
                check_password(password, user.password),
                credential is not None and check_password(pin, credential.encoded),
            )

        for user in listed:
            if accepts(user) != (True, True):
                raise CommandError(
                    f"{user.username} does not accept the password and PIN to publish. "
                    "Nothing was published."
                )
        for user in managers:
            if any(accepts(user)):
                raise CommandError(
                    f"{user.username} is an administrator and accepts a credential that "
                    "would be published. Give it a different password and PIN, then run "
                    "again. Nothing was published."
                )
        accounts = [
            (
                user.username,
                ", ".join(name.title() for name in sorted(g.name for g in user.groups.all()))
                or "No role",
            )
            for user in listed
        ]
        # Anyone can sign in to the listed accounts, so none may change its password or PIN.
        lock_credentials(actor=people["admin"], users=listed, reason=LOCK_REASON)
        change_announcement(
            actor=people["admin"],
            pin=admin_pin,
            expected_revision=current_announcement().revision,
            title=ANNOUNCEMENT_TITLE,
            body=_announcement_text(accounts, password, pin, reset_note()),
            published=True,
            reason=ANNOUNCEMENT_REASON,
        )
        self.stdout.write(
            "Sign-in announcement published for: " + ", ".join(username for username, _ in accounts)
        )

    def seed_journey(self, people, pin):
        rule = RuleSet.objects.filter(code="chemical").order_by("-version").first()
        if rule.status == "draft":
            if not PINCredential.objects.filter(user=people["quality"]).exists():
                raise CommandError("Enroll the existing demo_quality signature PIN first.")
            pin = pin or os.environ.get("DEMO_PIN") or getpass("Existing demo_quality PIN: ")
            rule = approve_rule(
                actor=people["quality"],
                pin=pin,
                rule=rule,
                expected_revision=rule.revision,
                reason="Synthetic demo policy review only.",
            )
        analyst = people["analyst"]
        with transaction.atomic():
            lot = Lot.objects.filter(number=LOT_NUMBER).first()
            if lot is None:
                lot = receive_lot(
                    actor=analyst,
                    number=LOT_NUMBER,
                    material="Synthetic reference powder",
                    rules=rule,
                    reason="Synthetic demo receipt.",
                    receipt={
                        "source": "supplier",
                        "supplier": Supplier.objects.get(code=SUPPLIERS[0][0]),
                        "supplier_lot": "SYN-SUP-LOT-0001",
                        "manufacturer": "",
                        "manufacturer_location": "",
                        "manufacturer_lot": "",
                        "shipment_ref": "DN-SYNTHETIC-0001",
                        "received_on": timezone.localdate(),
                        "quantity": Decimal("25"),
                        "quantity_unit": "kg",
                        "containers": 1,
                        "container_description": "Synthetic 25 kg fibre drum",
                        "condition": "acceptable",
                        "condition_notes": "",
                    },
                )
            sample = Sample.objects.filter(reference=SAMPLE_REFERENCE).first()
            if sample is None:
                sample = add_sample(
                    actor=analyst,
                    lot=lot,
                    reference=SAMPLE_REFERENCE,
                    collected_at=timezone.now(),
                    reason="Synthetic demo sampling.",
                )
            if not Result.objects.filter(sample=sample, test_code="identity").exists():
                record_result(
                    actor=analyst,
                    sample=sample,
                    reason="Synthetic demo observation.",
                    test_code="identity",
                    value=Decimal("1"),
                    unit="ratio",
                    lower_limit=Decimal("0.9"),
                    upper_limit=Decimal("1.1"),
                )
        self.stdout.write("Synthetic lot available; use demo_reviewer and demo_quality to sign.")
