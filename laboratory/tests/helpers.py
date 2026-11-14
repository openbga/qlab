"""Synthetic builders shared by laboratory and stability tests (synthetic data only)."""

from datetime import timedelta

from django.utils import timezone

from core.models import RuleSet
from laboratory import services
from quality.services import add_sample, receive_lot
from tests.receipts import on_site_receipt

PIN = "82519374"
PASSWORD = "synthetic-test-password-847"
ROLES = {
    "analyst": ["analyst"],
    "analyst2": ["analyst"],
    "reviewer": ["reviewer"],
    "reviewer2": ["reviewer"],
    "quality": ["quality"],
    "quality2": ["quality"],
    "auditor": ["auditor"],
    "admin": ["admin"],
}


def make_equipment(people, asset="BAL-001", *, requires_qualification=True, ready=True):
    """Register equipment; when `ready`, give it an accepted passing calibration (and approved
    qualification when required) from independent people."""
    equipment = services.register_equipment(
        actor=people["analyst"],
        asset_id=asset,
        description="Synthetic analytical balance",
        category="balance",
        location="Room 1",
        requires_qualification=requires_qualification,
        reason="Synthetic registration",
    )
    if ready:
        accept_new_calibration(people, equipment)
        if requires_qualification:
            qualify_equipment(people, equipment)
    return equipment


def accept_new_calibration(
    people, equipment, *, days_valid=90, outcome="pass", accept=True, performed_hours_ago=1
):
    calibration = services.record_calibration(
        actor=people["analyst"],
        equipment=equipment,
        performed_at=timezone.now() - timedelta(hours=performed_hours_ago),
        due_date=timezone.localdate() + timedelta(days=days_valid),
        outcome=outcome,
        standard_ref="CERT-SYN-1",
        certificate_ref="",
        certificate_url="",
        tolerance_note="Synthetic",
        reason="Synthetic calibration",
    )
    if accept:
        calibration = services.accept_calibration(
            actor=people["reviewer"],
            pin=PIN,
            calibration=calibration,
            expected_revision=calibration.revision,
            reason="Evidence checked",
        )
    return calibration


def qualify_equipment(people, equipment, *, activity="IQ/OQ/PQ"):
    today = timezone.localdate()
    qualification = services.record_qualification(
        actor=people["analyst"],
        equipment=equipment,
        activity=activity,
        scope_note="",
        evidence_ref="QUAL-SYN-1",
        evidence_url="",
        valid_from=today - timedelta(days=30),
        valid_until=today + timedelta(days=365),
        reason="Synthetic qualification evidence",
    )
    return services.approve_qualification(
        actor=people["quality"],
        pin=PIN,
        qualification=qualification,
        expected_revision=qualification.revision,
        reason="Independent approval",
    )


def qualify_analyst(people, user, activity="HPLC-ASSAY", *, days=365):
    today = timezone.localdate()
    qualification = services.record_qualification(
        actor=people["reviewer"],
        user=user,
        activity=activity,
        scope_note="",
        evidence_ref="TRAIN-SYN-1",
        evidence_url="",
        valid_from=today - timedelta(days=30),
        valid_until=today + timedelta(days=days),
        reason="Synthetic training record",
    )
    return services.approve_qualification(
        actor=people["quality"],
        pin=PIN,
        qualification=qualification,
        expected_revision=qualification.revision,
        reason="Independent approval",
    )


def make_reagent(people, identifier="RG-001", *, release=True, expiry_days=120, **overrides):
    today = timezone.localdate()
    values = {
        "identifier": identifier,
        "kind": "reagent",
        "name": "Synthetic buffer",
        "supplier": "Synthetic Supply",
        "lot_number": "SUP-1",
        "received_on": today - timedelta(days=5),
        "expiry_date": today + timedelta(days=expiry_days),
        "assigned_purity": None,
        "purity_unit": "",
        "parent": None,
        "preparation_note": "",
        "certificate_ref": "COA-SYN-1",
        "certificate_url": "",
        "reason": "Synthetic receipt",
    }
    values.update(overrides)
    lot = services.receive_reagent(actor=people["analyst"], **values)
    if release:
        lot = services.release_reagent(
            actor=people["reviewer"],
            pin=PIN,
            reagent=lot,
            expected_revision=lot.revision,
            reason="Certificate and expiry checked",
        )
    return lot


def run_interleaved(monkeypatch, module, hook_name, first, second, *, pause=0.5):
    """Run `first` here; when it reaches `module.hook_name` (holding its locks by then), start
    `second` in another thread and give it `pause` seconds to queue on those locks before `first`
    continues to commit. Returns each call's result or exception; a lock cycle shows up as
    PostgreSQL's "deadlock detected" error in one of them."""
    import threading
    import time

    from django.db import connection

    main, started, outcome = threading.current_thread(), threading.Event(), {}
    real = getattr(module, hook_name)

    def run_second():
        try:
            outcome["second"] = second()
        except Exception as exc:  # reported to the asserting test
            outcome["second"] = exc
        finally:
            connection.close()

    worker = threading.Thread(target=run_second)

    def hook(*args, **kwargs):
        if threading.current_thread() is main and not started.is_set():
            started.set()
            worker.start()
            time.sleep(pause)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, hook_name, hook)
    try:
        outcome["first"] = first()
    except Exception as exc:
        outcome["first"] = exc
    finally:
        if started.is_set():
            worker.join(30)
    monkeypatch.setattr(module, hook_name, real)
    assert started.is_set(), f"{hook_name} was never reached"
    return outcome


def make_rules(people, code="synthetic-rules"):
    return RuleSet.objects.create(
        code=code,
        segment="chemical",
        author=people["quality"],
        status="approved",
        effective_from=timezone.now() - timedelta(days=1),
        effective_until=timezone.now() + timedelta(days=365),
        policy={
            "required_tests": ["identity"],
            "review_meaning": "reviewed",
            "disposition_meaning": "approved",
        },
    )


def make_lot(people, number="SYN-LOT-1"):
    return receive_lot(
        actor=people["analyst"],
        number=number,
        material="Synthetic powder",
        rules=make_rules(people, f"rules-{number}"),
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )


def make_sample(people, lot=None, reference="SYN-S-1", collected_at=None):
    lot = lot or make_lot(people)
    return add_sample(
        actor=people["analyst"],
        lot=lot,
        reference=reference,
        collected_at=collected_at or timezone.now(),
        reason="Synthetic sample",
    )
