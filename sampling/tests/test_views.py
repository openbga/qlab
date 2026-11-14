"""Sampling pages: holds, assignment, sampling entry, corrections and role boundaries."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from catalog.tests.factories import (
    approve,
    approved_rules,
    approved_specification,
    commit_first_on_save,
    material,
    window,
)
from core.models import AuditEvent
from quality.models import Lot, Sample
from quality.services import receive_lot
from sampling import services
from sampling.models import LotAssignment, SamplingPlan, SamplingPlanRevision, SamplingRecord
from tests.receipts import on_site_receipt

from .test_services import plan_revision

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def lot(people):
    return receive_lot(
        actor=people["analyst"],
        number="SYN-WEB-LOT",
        material="Synthetic syn-api-001",
        rules=approved_rules(people["author"]),
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )


def sampling_data(**overrides):
    data = {
        "reference": "SYN-WEB-S1",
        "sampled_at": (timezone.now() - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M"),
        "location": "Booth 2",
        "containers_total": "4",
        "containers_sampled": "3",
        "container_ids": "C1, C2, C4",
        "quantity": "75.5",
        "quantity_unit": "g",
        "deviation": "",
        "reason": "Routine sampling",
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("name", ["sampling:lots", "sampling:plans"])
@pytest.mark.parametrize("role", ["analyst", "reviewer", "auditor", "author"])
def test_lists_readable(client, people, lot, name, role):
    client.force_login(people[role])
    assert client.get(reverse(name)).status_code == 200


def test_unassigned_lot_shows_hold_and_no_sampling_action(client, people, lot):
    client.force_login(people["analyst"])
    body = client.get(reverse("sampling:lot", args=[lot.pk])).content.decode()
    assert "Applicability hold: no requirements assigned" in body
    assert reverse("sampling:sampling_new", args=[lot.pk]) not in body
    response = client.get(reverse("sampling:sampling_new", args=[lot.pk]))
    assert response.status_code == 302
    listing = client.get(reverse("sampling:lots"), {"status": "none"}).content.decode()
    assert "SYN-WEB-LOT" in listing


def test_assign_hold_then_ready_then_sample_and_correct(client, people, lot):
    mat = material(people["author"])
    client.force_login(people["analyst"])
    assign_url = reverse("sampling:assign", args=[lot.pk])
    form = client.get(assign_url)
    assert f'value="{mat.pk}" selected' in form.content.decode()
    held = client.post(
        assign_url, {"material": mat.pk, "stage": "incoming", "scope": "general", "reason": "x"}
    )
    assert held.status_code == 302
    detail = client.get(reverse("sampling:lot", args=[lot.pk])).content.decode()
    assert "Applicability hold" in detail and "No specification exists" in detail

    approved_specification(people["author"], people["approver"], mat)
    approve(plan_revision(people["author"], mat), people["approver"])
    client.post(
        assign_url,
        {"material": mat.pk, "stage": "incoming", "scope": "general", "reason": "Resolved"},
    )
    assert LotAssignment.objects.filter(lot=lot).count() == 2
    detail = client.get(reverse("sampling:lot", args=[lot.pk])).content.decode()
    assert "Required tests frozen" in detail and "Earlier requirement assignments" in detail

    new_url = reverse("sampling:sampling_new", args=[lot.pk])
    short = client.post(new_url, sampling_data(containers_sampled="1"))
    assert short.status_code == 422
    assert "Record a deviation" in short.content.decode()
    assert "C1, C2, C4" in short.content.decode()
    ok = client.post(new_url, sampling_data())
    assert ok.status_code == 302
    record = SamplingRecord.objects.get()
    assert record.containers_required == 3

    correct_url = reverse("sampling:sampling_correct", args=[record.pk])
    data = sampling_data(container_ids="C1, C3, C4", reason="Transcription error")
    data.pop("reference")
    assert client.post(correct_url, data).status_code == 302
    detail = client.get(reverse("sampling:lot", args=[lot.pk])).content.decode()
    assert "Corrected" in detail and f"Corrects record {record.pk}" in detail


@pytest.mark.parametrize("role", ["reviewer", "auditor", "admin"])
def test_sampling_actions_denied(client, people, lot, role):
    client.force_login(people[role])
    assert client.get(reverse("sampling:assign", args=[lot.pk])).status_code == 403
    assert client.get(reverse("sampling:sampling_new", args=[lot.pk])).status_code == 403
    assert client.get(reverse("sampling:plan_new")).status_code == 403


def test_plan_approval_web_blocks_author(client, people):
    mat = material(people["author"])
    revision = plan_revision(people["author"], mat)
    client.force_login(people["author"])
    assert client.get(reverse("sampling:plan_approve", args=[revision.pk])).status_code == 403
    body = client.get(reverse("sampling:plan", args=[revision.plan_id])).content.decode()
    assert "Another quality approver must sign this draft." in body


def test_ineligible_action_pages_redirect_on_get(client, people, lot):
    from quality.models import Lot

    Lot.objects.filter(pk=lot.pk).update(state="released")
    client.force_login(people["analyst"])
    response = client.get(reverse("sampling:assign", args=[lot.pk]))
    assert response.status_code == 302


def _plan_data(code, mat):
    start, end = window()
    return {
        "code": code,
        "title": "Synthetic race plan",
        "material": mat.pk,
        "stage": "incoming",
        "basis": "sqrt_plus_one",
        "parameter": "",
        "minimum_quantity": "50",
        "quantity_unit": "g",
        "instructions": "Sample from the top third.",
        "rationale": "Synthetic plan for testing only.",
        "effective_from": start.strftime("%Y-%m-%dT%H:%M"),
        "effective_until": end.strftime("%Y-%m-%dT%H:%M"),
        "reason": "New",
    }


def _ready_for_sampling(people, lot):
    mat = material(people["author"])
    approved_specification(people["author"], people["approver"], mat)
    approve(plan_revision(people["author"], mat), people["approver"])
    services.assign_requirements(
        actor=people["analyst"], lot=lot, material=mat, stage="incoming", reason="Ready"
    )


@pytest.mark.parametrize("kind", ["plan code", "plan applicability", "sample reference"])
def test_concurrent_duplicate_is_a_form_error(client, people, lot, monkeypatch, kind):
    """A plan or sample reference committed by another request after every check of this one
    has passed is caught by its constraint and shown as a conflict; nothing of this one is saved."""
    author, analyst = people["author"], people["analyst"]
    if kind == "sample reference":
        _ready_for_sampling(people, lot)
        other = receive_lot(
            actor=analyst,
            number="SYN-WEB-LOT-2",
            material="Synthetic syn-api-001",
            rules=lot.rules,
            reason="Synthetic receipt",
            receipt=on_site_receipt(),
        )
        user, model = analyst, Sample
        url, data = reverse("sampling:sampling_new", args=[lot.pk]), sampling_data()

        def competitor():
            Sample.objects.create(
                lot=other, reference="SYN-WEB-S1", collected_at=timezone.now(), created_by=analyst
            )
    else:
        mat, elsewhere = material(author), material(author, code="syn-api-002")
        user, model = author, SamplingPlan
        url, data = reverse("sampling:plan_new"), _plan_data("plan-race", mat)
        code, target = ("plan-race", elsewhere) if kind == "plan code" else ("plan-o", mat)

        def competitor():
            SamplingPlan.objects.create(
                code=code,
                title="Other request",
                material=target,
                stage="incoming",
                created_by=author,
            )

    commit_first_on_save(monkeypatch, model, competitor)
    before = AuditEvent.objects.count(), Lot.objects.get(pk=lot.pk).revision
    client.force_login(user)
    response = client.post(url, data)
    assert response.status_code == 422
    assert "Another request saved a conflicting record" in response.content.decode()
    assert model.objects.count() == 1
    assert (
        not SamplingRecord.objects.exists()
        and not SamplingPlanRevision.objects.filter(plan__code="plan-race").exists()
    )
    assert (AuditEvent.objects.count(), Lot.objects.get(pk=lot.pk).revision) == before


def test_unexpected_unique_violation_while_sampling_is_raised(client, people, lot, monkeypatch):
    """A unique violation outside the expected duplicates (a repeated audit event id) is an
    integrity fault: it is raised, not shown as a conflict, and the sampling rolls back."""
    from django.db import IntegrityError

    _ready_for_sampling(people, lot)
    real = services.record_event

    def record_event(**kwargs):
        event = real(**kwargs)
        AuditEvent.objects.create(
            id=event.id,
            actor=event.actor,
            action=event.action,
            object_type=event.object_type,
            object_id=event.object_id,
        )
        return event

    monkeypatch.setattr(services, "record_event", record_event)
    client.force_login(people["analyst"])
    with pytest.raises(IntegrityError, match="core_auditevent_pkey"):
        client.post(reverse("sampling:sampling_new", args=[lot.pk]), sampling_data())
    assert not Sample.objects.exists() and not SamplingRecord.objects.exists()
