"""Sampling plan, lot requirement and sampling provenance contracts against PostgreSQL."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from catalog.services import ApplicabilityHold, digest
from catalog.tests.factories import (
    approve,
    approved_rules,
    approved_specification,
    material,
    window,
)
from core.models import AuditEvent
from quality.models import Lot, Sample
from quality.services import receive_lot
from sampling import services
from sampling.models import LotAssignment, SamplingPlanRevision, SamplingRecord
from sampling.services import containers_required, current_requirements
from tests.receipts import on_site_receipt

pytestmark = pytest.mark.django_db(transaction=True)


def plan_revision(actor, mat, stage="incoming", basis="sqrt_plus_one", parameter=None, **extra):
    start, end = window()
    fields = {
        "basis": basis,
        "parameter": parameter,
        "minimum_quantity": Decimal("50"),
        "quantity_unit": "g",
        "instructions": "Sample from the top third with a clean thief; label each container.",
        "rationale": "Synthetic plan for testing only.",
        "effective_from": start,
        "effective_until": end,
    }
    fields.update(extra)
    return services.create_plan(
        actor=actor,
        code=f"plan-{mat.code}-{stage}",
        title="Synthetic plan",
        material=mat,
        stage=stage,
        reason="Synthetic plan",
        **fields,
    )[1]


@pytest.fixture
def ready(people):
    mat = material(people["author"])
    spec = approved_specification(people["author"], people["approver"], mat)
    plan = approve(plan_revision(people["author"], mat), people["approver"])
    rules = approved_rules(people["author"])
    lot = receive_lot(
        actor=people["analyst"],
        number="SYN-LOT-A1",
        material=mat.name,
        rules=rules,
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )
    return {"material": mat, "spec": spec, "plan": plan, "rules": rules, "lot": lot}


def assign(people, ready, actor="analyst", **extra):
    return services.assign_requirements(
        actor=people[actor],
        lot=ready["lot"],
        material=ready["material"],
        stage="incoming",
        reason="Assign approved requirements",
        **extra,
    )


def sample(people, ready, reference="SYN-S-1", **extra):
    fields = {
        "actor": people["analyst"],
        "lot": ready["lot"],
        "reference": reference,
        "sampled_at": timezone.now() - timedelta(minutes=5),
        "containers_total": 9,
        "containers_sampled": 4,
        "container_ids": "C1, C2, C5, C9",
        "quantity": Decimal("60"),
        "quantity_unit": "g",
        "location": "Sampling booth 1",
        "reason": "Routine incoming sampling",
    }
    fields.update(extra)
    return services.record_sampling(**fields)


@pytest.mark.parametrize(
    "basis, parameter, total, expected",
    [
        ("sqrt_plus_one", None, 1, 1),
        ("sqrt_plus_one", None, 4, 3),
        ("sqrt_plus_one", None, 9, 4),
        ("sqrt_plus_one", None, 10, 5),
        ("sqrt_plus_one", None, 100, 11),
        ("all", None, 7, 7),
        ("fixed", Decimal("3"), 2, 2),
        ("fixed", Decimal("3"), 20, 3),
        ("percent", Decimal("10"), 15, 2),
        ("percent", Decimal("10"), 1, 1),
        ("percent", Decimal("12.5"), 8, 1),
    ],
)
def test_containers_required(basis, parameter, total, expected):
    assert containers_required(basis, parameter, total) == expected


@pytest.mark.parametrize(
    "basis, parameter",
    [
        ("fixed", None),
        ("fixed", Decimal("2.5")),
        ("percent", Decimal("101")),
        ("all", Decimal("1")),
    ],
)
def test_plan_shape_rejected(people, basis, parameter):
    mat = material(people["author"])
    with pytest.raises(ValidationError):
        plan_revision(people["author"], mat, basis=basis, parameter=parameter)


def test_plan_approval_independent_and_immutable(people):
    mat = material(people["author"])
    revision = plan_revision(people["author"], mat)
    with pytest.raises(PermissionDenied):
        approve(revision, people["author"])
    approved = approve(revision, people["approver"])
    assert approved.approved_content["basis"] == "sqrt_plus_one"
    assert approved.approved_hash == digest(approved.approved_content)
    with pytest.raises(DatabaseError), transaction.atomic():
        SamplingPlanRevision.objects.filter(pk=approved.pk).update(rationale="tampered")


def test_assignment_freezes_payload_and_bumps_lot_revision(people, ready):
    before = Lot.objects.get(pk=ready["lot"].pk).revision
    assignment = assign(people, ready)
    assert assignment.status == "ready"
    assert assignment.payload_hash == digest(assignment.payload)
    assert assignment.payload["specification"]["revision_id"] == ready["spec"].pk
    assert assignment.payload["sampling_plan"]["revision_id"] == ready["plan"].pk
    assert assignment.payload["lot"]["number"] == "SYN-LOT-A1"
    assert current_requirements(ready["lot"]) == assignment.payload
    assert Lot.objects.get(pk=ready["lot"].pk).revision == before + 1
    event = AuditEvent.objects.get(action="lot.requirements_assigned")
    assert event.after["payload_hash"] == assignment.payload_hash


def test_missing_plan_and_scope_hold_lot(people, ready):
    with pytest.raises(ApplicabilityHold, match="No specification or sampling"):
        current_requirements(ready["lot"])
    held = assign(people, ready, scope="eu-market")
    assert held.status == "hold"
    assert held.payload is None
    assert any("scope eu-market" in reason for reason in held.hold_reasons)
    with pytest.raises(ApplicabilityHold):
        current_requirements(ready["lot"])
    with pytest.raises(ApplicabilityHold):
        sample(people, ready)
    assert not Sample.objects.exists()
    resolved = assign(people, ready)
    assert resolved.supersedes == held
    assert current_requirements(ready["lot"])["scope"] == "general"


def test_missing_sampling_plan_is_a_hold(people):
    mat = material(people["author"])
    approved_specification(people["author"], people["approver"], mat)
    lot = receive_lot(
        actor=people["analyst"],
        number="SYN-LOT-NOPLAN",
        material=mat.name,
        rules=approved_rules(people["author"]),
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )
    held = services.assign_requirements(
        actor=people["analyst"], lot=lot, material=mat, stage="incoming", reason="Assign"
    )
    assert held.hold_reasons == [f"No sampling plan exists for {mat.code} at stage incoming."]


def test_assignment_role_and_state_boundaries(people, ready):
    for role in ("reviewer", "auditor", "admin"):
        with pytest.raises(PermissionDenied):
            assign(people, ready, actor=role)
    Lot.objects.filter(pk=ready["lot"].pk).update(state="released")
    with pytest.raises(ValidationError, match="quarantined"):
        assign(people, ready)
    assert not LotAssignment.objects.exists()


def test_sampling_records_provenance_and_creates_sample(people, ready):
    assignment = assign(people, ready)
    record = sample(people, ready)
    assert record.sample.reference == "SYN-S-1"
    assert record.sample.lot_id == ready["lot"].pk
    assert record.containers_required == 4
    assert record.plan_revision == ready["plan"]
    assert record.assignment == assignment
    assert record.sampled_by == record.recorded_by == people["analyst"]
    assert AuditEvent.objects.filter(action="sampling.recorded", object_id=str(record.pk)).exists()
    assert AuditEvent.objects.filter(action="sample.collected").exists()


def test_shortfall_requires_deviation(people, ready):
    assign(people, ready)
    with pytest.raises(ValidationError) as caught:
        sample(people, ready, containers_sampled=2, quantity=Decimal("10"))
    message = caught.value.message_dict["deviation"][0]
    assert "requires 4 containers" in message and "at least 50 g" in message
    assert not Sample.objects.exists()
    record = sample(
        people,
        ready,
        containers_sampled=2,
        quantity=Decimal("10"),
        deviation="Two containers damaged in transit; QA notified (synthetic).",
    )
    assert record.deviates


@pytest.mark.parametrize(
    "extra, field",
    [
        ({"containers_sampled": 10}, "containers_sampled"),
        ({"quantity_unit": "kg"}, "quantity_unit"),
        ({"sampled_at": timezone.now() + timedelta(days=1)}, "sampled_at"),
    ],
)
def test_sampling_input_errors(people, ready, extra, field):
    assign(people, ready)
    with pytest.raises(ValidationError) as caught:
        sample(people, ready, **extra)
    assert field in caught.value.message_dict
    assert not SamplingRecord.objects.exists()


def test_sampling_denied_to_non_analyst(people, ready):
    assign(people, ready)
    with pytest.raises(PermissionDenied):
        sample(people, ready, actor=people["reviewer"])


def test_correction_preserves_original(people, ready):
    assign(people, ready)
    original = sample(people, ready)
    correction = services.correct_sampling(
        actor=people["dual"],
        record=original,
        reason="Container IDs transcribed incorrectly",
        sampled_at=original.sampled_at,
        containers_total=9,
        containers_sampled=4,
        container_ids="C1, C2, C6, C9",
        quantity=Decimal("60"),
        quantity_unit="g",
        location="Sampling booth 1",
    )
    original.refresh_from_db()
    assert original.container_ids == "C1, C2, C5, C9"
    assert correction.corrects == original
    assert correction.sample == original.sample
    assert correction.sampled_by == people["analyst"]
    assert correction.recorded_by == people["dual"]
    with pytest.raises(ValidationError, match="already corrected"):
        services.correct_sampling(
            actor=people["analyst"],
            record=original,
            reason="Again",
            sampled_at=original.sampled_at,
            containers_total=9,
            containers_sampled=4,
            container_ids="C1",
            quantity=Decimal("60"),
            quantity_unit="g",
            location="Booth",
        )
    event = AuditEvent.objects.get(action="sampling.corrected")
    assert event.before["container_ids"] == "C1, C2, C5, C9"


@pytest.mark.parametrize("model", [LotAssignment, SamplingRecord])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_sampling_evidence_database_guards(people, ready, model, operation):
    assign(people, ready)
    sample(people, ready)
    obj = model.objects.first()
    with pytest.raises(DatabaseError), transaction.atomic():
        queryset = model.objects.filter(pk=obj.pk)
        if operation == "update":
            queryset.update(reason="tampered")
        else:
            queryset.delete()
    assert model.objects.filter(pk=obj.pk, reason__startswith=obj.reason[:5]).exists()


def test_assignment_chain_cannot_fork(people, ready):
    """Each assignment supersedes the previous one; a second successor is rejected."""
    first = assign(people, ready)
    second = assign(people, ready, actor="author")
    assert second.supersedes == first
    with pytest.raises(IntegrityError), transaction.atomic():
        LotAssignment.objects.create(
            lot=ready["lot"],
            material=ready["material"],
            stage="incoming",
            status="hold",
            hold_reasons=["x"],
            supersedes=first,
            reason="Fork attempt",
            assigned_by=people["analyst"],
        )


def test_sampling_outside_plan_effective_period_rejected(people, ready):
    assign(people, ready)
    with pytest.raises(ValidationError) as caught:
        sample(people, ready, sampled_at=timezone.now() - timedelta(days=2))
    assert "not effective" in caught.value.message_dict["sampled_at"][0]
    assert not Sample.objects.exists()
