"""Administrative visibility never confers scientific authority or self-review permission."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from core.models import AuditEvent, AuditReview, ElectronicSignature, RuleSet
from core.services import approve_rule, review_audit, save_rule, set_pin
from quality.models import Lot, Result, Sample
from quality.services import add_sample, dispose_lot, receive_lot, record_result, review_result
from tests.receipts import on_site_receipt

pytestmark = pytest.mark.django_db(transaction=True)
PIN = "83529174"
PASSWORD = "Synthetic-admin-boundaries-2026!"


@pytest.fixture
def records(django_user_model, settings):
    settings.DEBUG = True
    people = {}
    for name, roles in {
        "admin": ["admin"],
        "author": ["quality"],
        "approver": ["quality", "reviewer"],
        "analyst": ["analyst"],
        # Receives the lot, so "analyst" authors its test data only.
        "receiver": ["analyst"],
    }.items():
        user = django_user_model.objects.create_user(name, password=PASSWORD)
        user.groups.add(*[Group.objects.get_or_create(name=r)[0] for r in roles])
        set_pin(actor=user, pin=PIN, password=PASSWORD)
        people[name] = user
    fields = {
        "code": "synthetic-admin-test",
        "segment": "chemical",
        "policy": {
            "required_tests": ["identity"],
            "review_meaning": "reviewed",
            "disposition_meaning": "approved",
        },
        "effective_from": timezone.now() - timedelta(days=1),
        "effective_until": timezone.now() + timedelta(days=30),
        "reason": "Synthetic policy",
    }
    draft = save_rule(actor=people["author"], **fields)
    approved = approve_rule(
        actor=people["approver"],
        pin=PIN,
        rule=draft,
        expected_revision=draft.revision,
        reason="Independent policy review",
    )
    draft = save_rule(actor=people["author"], **{**fields, "code": "synthetic-draft"})
    lot = receive_lot(
        actor=people["receiver"],
        number="SYN-ADMIN-001",
        material="Synthetic powder",
        rules=approved,
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )
    sample = add_sample(
        actor=people["analyst"],
        lot=lot,
        reference="SYN-ADMIN-S001",
        collected_at=timezone.now(),
        reason="Synthetic sample",
    )
    result = record_result(
        actor=people["analyst"],
        sample=sample,
        test_code="identity",
        value=Decimal("1"),
        unit="ratio",
        lower_limit=Decimal("0.9"),
        upper_limit=Decimal("1.1"),
        reason="Synthetic observation",
    )
    return people, draft, lot, sample, result


def test_admin_reads_real_rules_lots_audit_filters_and_export_without_actions(client, records):
    people, draft, lot, _, result = records
    client.force_login(people["admin"])
    listing = client.get(reverse("quality:lot_list"), {"q": "SYN-ADMIN"})
    assert listing.status_code == 200 and lot.number.encode() in listing.content
    assert b"New material lot</a>" not in listing.content
    detail = client.get(reverse("quality:lot_detail", args=[lot.pk]))
    assert detail.status_code == 200 and b"identity" in detail.content
    for action in [
        b"Add sample</a>",
        b"Record result</a>",
        b"Review result</a>",
        b"Review disposition</a>",
        b"Issue certificate of analysis</a>",
    ]:
        assert action not in detail.content
    rules = client.get(reverse("core:rules"))
    assert rules.status_code == 200 and str(draft).encode() in rules.content
    assert b"Create draft</button>" not in rules.content
    assert b"Review and approve</a>" not in rules.content
    event = AuditEvent.objects.get(action="result.recorded", object_id=str(result.pk))
    query = {
        "actor": people["analyst"].pk,
        "action": "result.recorded",
        "object_type": "quality.result",
        "object_id": result.pk,
    }
    audit = client.get(reverse("core:audit"), query)
    assert audit.status_code == 200 and audit.context["page"].paginator.count == 1
    assert b"Synthetic observation" in audit.content
    for action in [b'name="events"', b'name="conclusion"', b"Record independent review</button>"]:
        assert action not in audit.content
    exported = client.get(reverse("core:audit"), {**query, "export": "csv"})
    assert exported.status_code == 200 and exported["Content-Type"] == "text/csv"
    assert str(event.pk).encode() in exported.content
    assert not AuditReview.objects.exists()


def test_admin_direct_mutations_and_action_forms_are_denied(client, records):
    people, draft, lot, sample, result = records
    client.force_login(people["admin"])
    before = (
        RuleSet.objects.count(),
        Lot.objects.count(),
        Sample.objects.count(),
        Result.objects.count(),
        AuditReview.objects.count(),
        ElectronicSignature.objects.count(),
        AuditEvent.objects.count(),
    )
    mutations = [
        ("quality:lot_new", []),
        ("quality:sample_new", [lot.pk]),
        ("quality:result_new", [sample.pk]),
        ("quality:review", [result.pk]),
        ("quality:disposition", [lot.pk]),
        ("core:rule_approve", [draft.pk]),
    ]
    for route, args in mutations:
        url = reverse(route, args=args)
        assert client.get(url).status_code == 403
        assert (
            client.post(
                url,
                {
                    "pin": PIN,
                    "signature_username": people["admin"].username,
                    "reason": "Must be denied",
                },
            ).status_code
            == 403
        )
    assert client.post(reverse("core:rules"), {}).status_code == 403
    assert client.post(reverse("core:audit"), {}).status_code == 403
    assert before == (
        RuleSet.objects.count(),
        Lot.objects.count(),
        Sample.objects.count(),
        Result.objects.count(),
        AuditReview.objects.count(),
        ElectronicSignature.objects.count(),
        AuditEvent.objects.count(),
    )
    with pytest.raises(PermissionDenied):
        save_rule(
            actor=people["admin"],
            code="denied",
            segment="chemical",
            policy=draft.policy,
            effective_from=draft.effective_from,
            reason="Direct service attempt",
        )
    with pytest.raises(PermissionDenied):
        review_audit(
            actor=people["admin"],
            event_ids=[AuditEvent.objects.first().pk],
            conclusion="Direct service attempt",
        )
    # The seed command must deny admin even when every preset already exists and no save is needed.
    call_command("seed_rules", actor=people["author"].username)
    count = AuditEvent.objects.count()
    with pytest.raises(PermissionDenied):
        call_command("seed_rules", actor=people["admin"].username)
    assert AuditEvent.objects.count() == count


def test_admin_with_scientific_roles_gets_actions_but_cannot_self_review(client, records):
    people, draft, lot, _, result = records
    author = people["author"]
    author.groups.add(Group.objects.get_or_create(name="admin")[0])
    client.force_login(author)
    page = client.get(reverse("core:rules"))
    assert b"Create draft</button>" in page.content
    assert reverse("core:rule_approve", args=[draft.pk]).encode() not in page.content
    assert (
        client.post(
            reverse("core:rule_approve", args=[draft.pk]),
            {
                "revision": draft.revision,
                "pin": PIN,
                "signature_username": author.username,
                "reason": "Self approval still denied",
            },
        ).status_code
        == 403
    )
    own_event = AuditEvent.objects.get(action="rule.created", object_id=str(draft.pk))
    assert (
        client.post(
            reverse("core:audit"),
            {
                "events": [str(own_event.pk)],
                "conclusion": "Self review still denied",
            },
        ).status_code
        == 422
    )
    analyst = people["analyst"]
    analyst.groups.add(
        *[Group.objects.get_or_create(name=r)[0] for r in ["admin", "reviewer", "quality"]]
    )
    client.force_login(analyst)
    assert b"New material lot</a>" in client.get(reverse("quality:lot_list")).content
    body = client.get(reverse("quality:lot_detail", args=[lot.pk])).content
    assert b"Add sample</a>" in body and b"Review disposition</a>" in body
    assert b"Review result</a>" not in body
    with pytest.raises(ValidationError, match="own"):
        review_result(
            actor=analyst,
            pin=PIN,
            result=result,
            expected_revision=result.revision,
            reason="Self review attempt",
        )
    people["approver"].groups.add(Group.objects.get_or_create(name="admin")[0])
    review_result(
        actor=people["approver"],
        pin=PIN,
        result=result,
        expected_revision=result.revision,
        reason="Independent review",
    )
    lot.refresh_from_db()
    with pytest.raises(ValidationError, match="own"):
        dispose_lot(
            actor=analyst,
            pin=PIN,
            lot=lot,
            expected_revision=lot.revision,
            reason="Self disposition attempt",
        )
    # An admin+quality user can create drafts, and an independent admin+reviewer can review.
    response = client.post(
        reverse("core:rules"),
        {
            "code": "dual-role-created",
            "segment": "chemical",
            "policy": json.dumps(draft.policy),
            "effective_from": draft.effective_from.isoformat(),
            "effective_until": draft.effective_until.isoformat(),
            "reason": "Authorized draft",
        },
    )
    assert response.status_code == 302
    assert RuleSet.objects.filter(code="dual-role-created", author=analyst).exists()

    lot.refresh_from_db()
    dispose_lot(
        actor=people["approver"],
        pin=PIN,
        lot=lot,
        expected_revision=lot.revision,
        reason="Independent admin-plus-quality disposition",
    )
    client.force_login(people["admin"])
    released = client.get(reverse("quality:lot_detail", args=[lot.pk]))
    assert released.status_code == 200
    assert b"Released" in released.content and b"approved" in released.content
    assert b"Issue certificate of analysis</a>" not in released.content
