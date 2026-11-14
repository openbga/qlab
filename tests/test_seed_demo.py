from io import StringIO

import pytest
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError

from catalog.models import Material, MethodRevision, SpecificationRevision
from catalog.services import create_material
from core.models import AuditEvent, ElectronicSignature, PINCredential, RuleSet
from quality.models import Lot, Result, Sample
from quality.services import current_receipt
from sampling.models import SamplingPlanRevision
from suppliers.models import Supplier
from suppliers.services import create_supplier

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "Synthetic-seed-password-2026!"
PIN = "84621357"


@pytest.fixture
def demo_env(settings, monkeypatch, django_user_model):
    settings.DEBUG = True
    monkeypatch.setenv("DEMO_PASSWORD", PASSWORD)
    monkeypatch.setenv("DEMO_PIN", PIN)
    return django_user_model.objects.create_user("bootstrap", is_superuser=True)


def test_demo_uses_services_and_is_idempotent(demo_env, django_user_model, monkeypatch):
    output = StringIO()
    warnings = StringIO()
    call_command("seed_demo", actor=demo_env.username, journey=True, stdout=output, stderr=warnings)
    assert "no admin laboratory role" in warnings.getvalue()
    assert "assign_roles bootstrap admin --actor bootstrap --reason" in warnings.getvalue()
    assert "replaces the complete role set" in warnings.getvalue()
    assert not demo_env.groups.exists()  # Seeding never grants its actor implicit authority.
    assert PASSWORD not in warnings.getvalue() and PIN not in warnings.getvalue()
    assert PASSWORD not in output.getvalue() and PIN not in output.getvalue()
    assert django_user_model.objects.filter(username__startswith="demo_").count() == 6
    hashes = {}
    for user in django_user_model.objects.filter(username__startswith="demo_"):
        credential = PINCredential.objects.get(user=user)
        assert user.check_password(PASSWORD)
        assert credential.encoded != PIN and check_password(PIN, credential.encoded)
        hashes[user.pk] = (user.password, credential.encoded)
    assert RuleSet.objects.filter(status="draft").count() == 4
    assert set(RuleSet.objects.values_list("author__username", flat=True)) == {"demo_config_author"}
    assert list(
        django_user_model.objects.get(username="demo_admin").groups.values_list("name", flat=True)
    ) == ["admin"]
    assert RuleSet.objects.get(code="chemical").status == "approved"
    signature = ElectronicSignature.objects.get()
    assert signature.signer.username == "demo_quality"
    assert signature.meaning == "approved" and signature.audit_event_id
    assert Result.objects.get().state == "recorded"
    assert Lot.objects.get().state == "quarantine"
    # The register names two synthetic suppliers, and the journey's lot came from the first.
    assert list(Supplier.objects.values_list("code", "created_by__username")) == [
        ("sup-syn-001", "demo_config_author"),
        ("sup-syn-002", "demo_config_author"),
    ]
    receipt = current_receipt(Lot.objects.get())
    assert (receipt.supplier.code, receipt.recorded_by.username) == ("sup-syn-001", "demo_analyst")
    quality_user = django_user_model.objects.get(username="demo_quality")
    unrelated = create_material(
        actor=quality_user,
        code="unrelated-existing",
        name="Unrelated synthetic material",
        kind="raw_material",
        reason="Existing unrelated configuration",
    )
    unrelated_before = Material.objects.filter(pk=unrelated.pk).values().get()
    profile_counts = (
        MethodRevision.objects.count(),
        SpecificationRevision.objects.count(),
        SamplingPlanRevision.objects.count(),
    )
    before = AuditEvent.objects.count()
    monkeypatch.setenv("DEMO_PASSWORD", "Changed-input-must-not-reset-2026!")
    monkeypatch.setenv("DEMO_PIN", "99999999")
    call_command("seed_demo", actor=demo_env.username, journey=True, stdout=StringIO())
    assert AuditEvent.objects.count() == before
    assert Material.objects.filter(pk=unrelated.pk).values().get() == unrelated_before
    assert profile_counts == (
        MethodRevision.objects.count(),
        SpecificationRevision.objects.count(),
        SamplingPlanRevision.objects.count(),
    )
    assert (Lot.objects.count(), Sample.objects.count(), Result.objects.count()) == (1, 1, 1)
    assert Supplier.objects.count() == 2 and Lot.objects.get().receipts.count() == 1
    for user in django_user_model.objects.filter(username__startswith="demo_"):
        assert hashes[user.pk] == (user.password, PINCredential.objects.get(user=user).encoded)


def test_demo_refuses_a_supplier_it_did_not_seed(demo_env, django_user_model):
    # A laboratory's own supplier under a seed code is never adopted or overwritten.
    owner = django_user_model.objects.create_user("lab_quality", password=PASSWORD)
    owner.groups.add(Group.objects.get_or_create(name="quality")[0])
    own = create_supplier(
        actor=owner,
        code="sup-syn-001",
        name="Unrelated synthetic supplier",
        location="Elsewhere, Exampleland",
        reason="Existing unrelated configuration",
    )
    before = AuditEvent.objects.count()
    with pytest.raises(CommandError, match="non-demo supplier collision: sup-syn-001"):
        call_command("seed_demo", actor=demo_env.username, stdout=StringIO(), stderr=StringIO())
    assert list(Supplier.objects.values_list("pk", "name")) == [(own.pk, own.name)]
    assert AuditEvent.objects.count() == before
    assert not django_user_model.objects.filter(username__startswith="demo_").exists()


def test_demo_refuses_production_and_non_demo_accounts(demo_env, settings, django_user_model):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("seed_demo", actor=demo_env.username)
    settings.DEBUG = True
    collision = django_user_model.objects.create_user("demo_quality", password=PASSWORD)
    with pytest.raises(CommandError, match="non-demo account"):
        call_command("seed_demo", actor=demo_env.username)
    assert django_user_model.objects.count() == 2
    collision.refresh_from_db()
    assert collision.check_password(PASSWORD)
    assert not AuditEvent.objects.exists()


def test_demo_default_keeps_all_presets_draft_and_rejects_bad_pin(demo_env, monkeypatch):
    monkeypatch.setenv("DEMO_PIN", "123")
    with pytest.raises(CommandError, match="8–32"):
        call_command("seed_demo", actor=demo_env.username)
    assert not AuditEvent.objects.exists()
    monkeypatch.setenv("DEMO_PIN", PIN)
    from django.contrib.auth.models import Group

    demo_env.groups.add(Group.objects.get_or_create(name="admin")[0])
    warnings = StringIO()
    call_command("seed_demo", actor=demo_env.username, stdout=StringIO(), stderr=warnings)
    assert not warnings.getvalue()
    assert RuleSet.objects.filter(status="draft").count() == 5
    assert not ElectronicSignature.objects.exists()
    assert not Lot.objects.exists()
    assert Material.objects.count() == SpecificationRevision.objects.count() == 5
    assert SamplingPlanRevision.objects.count() == 5
    assert MethodRevision.objects.count() > 0
    for model in (MethodRevision, SpecificationRevision, SamplingPlanRevision):
        assert not model.objects.exclude(status="draft").exists()
        assert set(model.objects.values_list("author__username", flat=True)) == {
            "demo_config_author"
        }


def test_legacy_demo_rule_author_is_preserved_without_admin_role_escalation(
    demo_env, django_user_model
):
    """Keep historical seeded revisions while new rule creation requires quality."""
    from datetime import timedelta

    from django.db import transaction
    from django.utils import timezone

    from accounts.services import provision_account
    from core.audit import record_event, snapshot
    from core.management.commands.seed_demo import MARKER
    from core.management.commands.seed_rules import SEED_REASON
    from core.services import set_pin

    admin = provision_account(
        actor=demo_env,
        username="demo_admin",
        password=PASSWORD,
        first_name="Synthetic",
        last_name="Admin",
        roles=["admin"],
        reason=MARKER,
    )
    set_pin(actor=admin, password=PASSWORD, pin=PIN)
    # Simulate the persisted older seed format; current services correctly prohibit its creation.
    with transaction.atomic():
        old = RuleSet.objects.create(
            code="chemical",
            segment="chemical",
            author=admin,
            effective_from=timezone.now(),
            effective_until=timezone.now() + timedelta(days=365),
            policy={
                "required_tests": ["identity"],
                "review_meaning": "reviewed",
                "disposition_meaning": "approved",
            },
        )
        event = record_event(
            actor=admin, action="rule.created", obj=old, after=snapshot(old), reason=SEED_REASON
        )
    previous = snapshot(old)
    credential = admin.password
    call_command("seed_demo", actor=demo_env.username, stdout=StringIO(), stderr=StringIO())
    old.refresh_from_db()
    admin.refresh_from_db()
    assert snapshot(old) == previous
    assert AuditEvent.objects.get(pk=event.pk).after == previous
    assert list(admin.groups.values_list("name", flat=True)) == ["admin"]
    assert admin.password == credential
    assert set(RuleSet.objects.exclude(pk=old.pk).values_list("author__username", flat=True)) == {
        "demo_config_author"
    }
    before = AuditEvent.objects.count()
    call_command("seed_demo", actor=demo_env.username, stdout=StringIO(), stderr=StringIO())
    assert AuditEvent.objects.count() == before


ADMIN_PASSWORD = "Synthetic-seed-admin-password-2026!"
ADMIN_PIN = "51739264"


def test_publish_accounts_announces_only_accounts_without_announcement_authority(
    demo_env, django_user_model, monkeypatch, client
):
    from accounts.announcements import MEANING, change_announcement, current_announcement
    from accounts.models import LoginAnnouncement

    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("DEMO_ADMIN_PIN", ADMIN_PIN)
    output = StringIO()
    call_command(
        "seed_demo",
        actor=demo_env.username,
        publish_accounts=True,
        stdout=output,
        stderr=StringIO(),
    )
    printed = output.getvalue()
    for secret in (PASSWORD, PIN, ADMIN_PASSWORD, ADMIN_PIN):
        assert secret not in printed
    listed = ["demo_analyst", "demo_auditor", "demo_config_author", "demo_quality", "demo_reviewer"]
    assert "Sign-in announcement published for: " + ", ".join(listed) in printed

    announcement = LoginAnnouncement.objects.get()
    assert announcement.published and announcement.title == "Demonstration accounts"
    for username in listed:
        assert f"`{username}`" in announcement.body
    assert "demo_admin" not in announcement.body and "bootstrap" not in announcement.body
    assert PASSWORD in announcement.body and PIN in announcement.body
    assert ADMIN_PASSWORD not in announcement.body and ADMIN_PIN not in announcement.body

    admin = django_user_model.objects.get(username="demo_admin")
    assert admin.check_password(ADMIN_PASSWORD) and not admin.check_password(PASSWORD)
    admin_pin = PINCredential.objects.get(user=admin).encoded
    assert check_password(ADMIN_PIN, admin_pin) and not check_password(PIN, admin_pin)
    signature = ElectronicSignature.objects.get(meaning=MEANING)
    assert signature.signer == admin and signature.revision == announcement.revision == 2

    page = client.get("/accounts/login/").content.decode()
    assert "<td><code>demo_reviewer</code></td><td>Reviewer</td>" in page
    assert "<td><code>demo_config_author</code></td><td>Quality</td>" in page
    assert (
        f"<pre><code>{PASSWORD}</code></pre>" in page and f"<pre><code>{PIN}</code></pre>" in page
    )
    assert "demo_admin" not in page
    # A published account signs in with the announced password and cannot change the notice.
    assert client.login(username="demo_quality", password=PASSWORD)
    assert client.get("/accounts/announcement/").status_code == 403

    # An administrator's later text is kept: a rerun neither replaces it nor asks for credentials.
    change_announcement(
        actor=admin,
        pin=ADMIN_PIN,
        expected_revision=announcement.revision,
        title="Edited",
        body="Edited by the administrator.",
        published=True,
        reason="Synthetic administrator edit",
    )
    for name in ("DEMO_PASSWORD", "DEMO_PIN", "DEMO_ADMIN_PASSWORD", "DEMO_ADMIN_PIN"):
        monkeypatch.delenv(name)
    before = AuditEvent.objects.count()
    output = StringIO()
    call_command("seed_demo", actor=demo_env.username, publish_accounts=True, stdout=output)
    assert "already has text; it was left unchanged" in output.getvalue()
    assert current_announcement().body == "Edited by the administrator."
    assert AuditEvent.objects.count() == before


def test_publish_accounts_refuses_credentials_that_open_an_announcement_manager(
    demo_env, django_user_model, monkeypatch
):
    from accounts.models import LoginAnnouncement

    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("DEMO_ADMIN_PIN", PIN)
    with pytest.raises(CommandError, match="different from the published accounts"):
        call_command("seed_demo", actor=demo_env.username, publish_accounts=True)
    monkeypatch.setenv("DEMO_ADMIN_PIN", ADMIN_PIN)
    for unshowable in (PASSWORD + " ", "```" + PASSWORD, PASSWORD + "\nsecond line"):
        monkeypatch.setenv("DEMO_PASSWORD", unshowable)
        with pytest.raises(CommandError, match="cannot be shown exactly"):
            call_command("seed_demo", actor=demo_env.username, publish_accounts=True)
    monkeypatch.setenv("DEMO_PASSWORD", PASSWORD)
    assert not django_user_model.objects.filter(username__startswith="demo_").exists()

    # Seeded without publication, demo_admin shares the demo password and PIN.
    monkeypatch.delenv("DEMO_ADMIN_PASSWORD")
    monkeypatch.delenv("DEMO_ADMIN_PIN")
    call_command("seed_demo", actor=demo_env.username, stdout=StringIO(), stderr=StringIO())
    assert not LoginAnnouncement.objects.exists()
    monkeypatch.setenv("DEMO_ADMIN_PIN", ADMIN_PIN)
    with pytest.raises(CommandError, match="demo_admin is an administrator and accepts"):
        call_command("seed_demo", actor=demo_env.username, publish_accounts=True, stdout=StringIO())

    # A listed account whose password was changed would be announced with a wrong credential.
    admin = django_user_model.objects.get(username="demo_admin")
    admin.set_password(ADMIN_PASSWORD)
    admin.save()
    PINCredential.objects.filter(user=admin).delete()
    reviewer = django_user_model.objects.get(username="demo_reviewer")
    reviewer.set_password("Changed-by-a-visitor-2026!")
    reviewer.save()
    with pytest.raises(CommandError, match="demo_reviewer does not accept"):
        call_command("seed_demo", actor=demo_env.username, publish_accounts=True, stdout=StringIO())
    assert not LoginAnnouncement.objects.filter(published=True).exists()
    assert not ElectronicSignature.objects.exists()
