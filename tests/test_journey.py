from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from core.models import AuditEvent, ElectronicSignature, RuleSet
from core.services import set_pin
from quality.models import Result
from quality.services import add_sample, dispose_lot, receive_lot, record_result, review_result
from tests.receipts import on_site_receipt

pytestmark = pytest.mark.django_db(transaction=True)
PIN = "12345678"


@pytest.fixture
def journey(django_user_model, settings):
    # The foundation manual-limit path is retained only for synthetic development use.
    settings.DEBUG = True
    people = {}
    for role in ["analyst", "reviewer", "quality"]:
        user = django_user_model.objects.create_user(role, password="test-password-2026")
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        set_pin(actor=user, pin=PIN, password="test-password-2026")
        people[role] = user
    # Someone else receives the lot, so the analyst below authors its test data only and each
    # independence rule is exercised on its own.
    receiver = django_user_model.objects.create_user("receiver", password="test-password-2026")
    receiver.groups.add(Group.objects.get(name="analyst"))
    rules = RuleSet.objects.create(
        code="synthetic",
        segment="chemical",
        author=people["quality"],
        status="approved",
        effective_from=timezone.now(),
        effective_until=timezone.now() + timedelta(days=365),
        policy={
            "required_tests": ["identity"],
            "review_meaning": "reviewed",
            "disposition_meaning": "approved",
        },
    )
    lot = receive_lot(
        actor=receiver,
        number="SYN-001",
        material="Synthetic powder",
        rules=rules,
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )
    sample = add_sample(
        actor=people["analyst"],
        lot=lot,
        reference="SYN-S001",
        collected_at=timezone.now(),
        reason="Synthetic sample",
    )
    result = record_result(
        actor=people["analyst"],
        sample=sample,
        reason="Synthetic measurement",
        test_code="identity",
        value=Decimal("1.0"),
        unit="ratio",
        lower_limit=Decimal("0.9"),
        upper_limit=Decimal("1.1"),
    )
    return people, lot, sample, result


def test_signed_journey_and_immutable_evidence(journey):
    people, lot, sample, result = journey
    reviewed = review_result(
        actor=people["reviewer"],
        pin=PIN,
        result=result,
        expected_revision=1,
        reason="Raw data checked",
    )
    assert reviewed.state == "reviewed"
    lot.refresh_from_db()
    released = dispose_lot(
        actor=people["quality"],
        pin=PIN,
        lot=lot,
        expected_revision=lot.revision,
        reason="All evidence checked",
    )
    assert released.state == "released"
    signatures = ElectronicSignature.objects.filter(object_type__startswith="quality.")
    assert signatures.count() == 2
    assert set(signatures.values_list("meaning", flat=True)) == {"reviewed", "approved"}
    assert all(s.content_hash and s.audit_event_id for s in signatures)
    for action in [
        lambda: Result.objects.filter(pk=result.pk).update(value=Decimal("2")),
        lambda: Result.objects.filter(pk=result.pk).delete(),
        lambda: type(sample).objects.filter(pk=sample.pk).update(reference="changed"),
        lambda: type(lot).objects.filter(pk=lot.pk).update(material="changed"),
    ]:
        with pytest.raises(DatabaseError), transaction.atomic():
            action()


def test_self_review_and_self_disposition_forbidden(journey):
    people, lot, _, result = journey
    actor = people["analyst"]
    actor.groups.add(Group.objects.get(name="reviewer"), Group.objects.get(name="quality"))
    with pytest.raises(ValidationError, match="own result"):
        review_result(actor=actor, pin=PIN, result=result, expected_revision=1, reason="Check")
    review_result(
        actor=people["reviewer"], pin=PIN, result=result, expected_revision=1, reason="Checked"
    )
    lot.refresh_from_db()
    with pytest.raises(ValidationError, match="own receipt, sampling or test data"):
        dispose_lot(actor=actor, pin=PIN, lot=lot, expected_revision=lot.revision, reason="Check")
    assert ElectronicSignature.objects.filter(object_type="quality.lot").count() == 0


def test_stale_signing_and_unreviewed_release_rejected(journey):
    people, lot, _, result = journey
    with pytest.raises(ValidationError, match="changed"):
        review_result(
            actor=people["reviewer"], pin=PIN, result=result, expected_revision=0, reason="Checked"
        )
    lot.refresh_from_db()
    with pytest.raises(ValidationError, match="independent review"):
        dispose_lot(
            actor=people["quality"],
            pin=PIN,
            lot=lot,
            expected_revision=lot.revision,
            reason="Check",
        )
    assert not ElectronicSignature.objects.exists()
    assert not AuditEvent.objects.filter(action__startswith="signed.").exists()


def test_permission_gate_and_out_of_specification(journey):
    people, lot, _, result = journey
    with pytest.raises(PermissionDenied):
        review_result(
            actor=people["analyst"], pin=PIN, result=result, expected_revision=1, reason="Check"
        )
    sample = add_sample(
        actor=people["analyst"],
        lot=lot,
        reference="SYN-OOS",
        collected_at=timezone.now(),
        reason="Second sample",
    )
    failed = record_result(
        actor=people["analyst"],
        sample=sample,
        reason="Failed measurement",
        test_code="identity",
        value=Decimal("2"),
        unit="ratio",
        lower_limit=Decimal("0.9"),
        upper_limit=Decimal("1.1"),
    )
    with pytest.raises(ValidationError, match="investigation"):
        review_result(
            actor=people["reviewer"], pin=PIN, result=failed, expected_revision=1, reason="Check"
        )


def test_journey_pages_require_roles(journey, client, django_user_model):
    people, lot, _, _ = journey
    assert client.get("/").status_code == 302
    outsider = django_user_model.objects.create_user("outsider", password="password")
    client.force_login(outsider)
    assert client.get("/").url == "/accounts/access/"
    assert client.get(f"/lots/{lot.pk}/").status_code == 403
    client.force_login(people["analyst"])
    assert client.get("/").status_code == 200
    assert client.get(f"/lots/{lot.pk}/").status_code == 200
