import datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from catalog.units import plain
from core.audit import record_event
from core.services import require_role, sign_transition, validate_rules

from .models import Lot, LotReceipt, ReceiptCondition, ReceiptSource, Result, Sample

# What a receipt states. Every key is required, exactly as entered; nothing is defaulted.
RECEIPT_FIELDS = (
    "source",
    "supplier",
    "supplier_lot",
    "manufacturer",
    "manufacturer_location",
    "manufacturer_lot",
    "shipment_ref",
    "received_on",
    "quantity",
    "quantity_unit",
    "containers",
    "container_description",
    "condition",
    "condition_notes",
)
RECEIPT_TEXT = (
    "supplier_lot",
    "manufacturer",
    "manufacturer_location",
    "manufacturer_lot",
    "shipment_ref",
    "container_description",
    "condition_notes",
)
OUTSIDE_SOURCE = ("supplier_lot", "manufacturer", "manufacturer_location", "manufacturer_lot")
RECEIPT_STALE = "The receipt details changed. Reload and review them before correcting."


def effective_rules(rules):
    validate_rules(rules)
    required = rules.policy["required_tests"]
    return required


def current_receipt(lot):
    """The lot's receipt details in force: the record that no correction has replaced."""
    return (
        LotReceipt.objects.filter(lot=lot, corrected_by__isnull=True)
        .select_related("supplier", "recorded_by")
        .first()
    )


def receipt_content(receipt):
    """Receipt details as audit evidence: exact text, plain decimals, the supplier by code."""
    return {
        "lot": receipt.lot_id,
        "source": receipt.source,
        "supplier": receipt.supplier.code if receipt.supplier_id else None,
        "supplier_lot": receipt.supplier_lot,
        "manufacturer": receipt.manufacturer,
        "manufacturer_location": receipt.manufacturer_location,
        "manufacturer_lot": receipt.manufacturer_lot,
        "shipment_ref": receipt.shipment_ref,
        "received_on": receipt.received_on.isoformat(),
        "quantity": plain(receipt.quantity),
        "quantity_unit": receipt.quantity_unit,
        "containers": receipt.containers,
        "container_description": receipt.container_description,
        "condition": receipt.condition,
        "condition_notes": receipt.condition_notes,
        "corrects": receipt.corrects_id,
    }


def _stated(content):
    return {key: value for key, value in content.items() if key != "corrects"}


def _receipt_values(values):
    """Check receipt details as a whole; field formats are checked again by the model."""
    if not isinstance(values, dict) or set(values) != set(RECEIPT_FIELDS):
        raise ValidationError("Receipt details are incomplete.")
    data = dict(values)
    for name in RECEIPT_TEXT:
        data[name] = (data[name] or "").strip()
    errors = {}
    if data["source"] == ReceiptSource.SUPPLIER:
        if data["supplier"] is None:
            errors["supplier"] = "Select the supplier the lot was received from."
    elif data["source"] == ReceiptSource.ON_SITE:
        if data["supplier"] is not None or any(data[name] for name in OUTSIDE_SOURCE):
            errors["source"] = (
                "Material made on site has no supplier, supplier lot or outside manufacturer."
            )
    else:
        errors["source"] = "Choose where the lot came from."
    if not data["manufacturer"] and (data["manufacturer_location"] or data["manufacturer_lot"]):
        errors["manufacturer"] = "Name the manufacturer when giving its location or lot number."
    received = data["received_on"]
    if not isinstance(received, datetime.date) or isinstance(received, datetime.datetime):
        errors["received_on"] = "Enter the date the lot was received."
    elif received > timezone.localdate():
        errors["received_on"] = "The date received cannot be in the future."
    quantity = data["quantity"]
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0:
        errors["quantity"] = "Enter an exact quantity greater than zero."
    containers = data["containers"]
    if isinstance(containers, bool) or not isinstance(containers, int) or containers < 1:
        errors["containers"] = "Enter the number of containers received, at least one."
    if not data["shipment_ref"]:
        errors["shipment_ref"] = "Enter the delivery or batch document."
    if not data["container_description"]:
        errors["container_description"] = "Describe the containers."
    if data["condition"] == ReceiptCondition.DISCREPANCY and not data["condition_notes"]:
        errors["condition_notes"] = "Describe the discrepancy found on receipt."
    if errors:
        raise ValidationError(errors)
    return data


def _lock_quarantined(actor, lot, refusal):
    # Signing locks the actor before the lot; serialize here before taking any record lock.
    # NO KEY UPDATE stays compatible with deferred foreign-key checks on this account.
    get_user_model().objects.select_for_update(no_key=True).get(pk=actor.pk)
    lot = Lot.objects.select_for_update().get(pk=lot.pk)
    if lot.state != "quarantine":
        raise ValidationError(refusal)
    return lot


def _add_receipt(*, actor, lot, reason, values, corrects=None):
    if not (reason or "").strip():
        raise ValidationError("A reason is required.")
    receipt = LotReceipt(
        lot=lot, recorded_by=actor, reason=reason, corrects=corrects, **_receipt_values(values)
    )
    if corrects is not None and _stated(receipt_content(receipt)) == _stated(
        receipt_content(corrects)
    ):
        raise ValidationError("The correction changes nothing.")
    receipt.full_clean()
    receipt.save()
    record_event(
        actor=actor,
        action="lot.receipt_corrected" if corrects else "lot.receipt_recorded",
        obj=receipt,
        reason=reason,
        before=receipt_content(corrects) if corrects else None,
        after=receipt_content(receipt),
    )
    return receipt


@transaction.atomic
def receive_lot(*, actor, number, material, rules, reason, receipt):
    """Receive a lot into quarantine together with its receipt details, or not at all."""
    require_role(actor, "analyst")
    effective_rules(rules)
    lot = Lot.objects.create(number=number, material=material, rules=rules, created_by=actor)
    record_event(
        actor=actor,
        action="lot.received",
        obj=lot,
        reason=reason,
        after={"number": number, "material": material, "rules": rules.pk},
    )
    _add_receipt(actor=actor, lot=lot, reason=reason, values=receipt)
    return lot


@transaction.atomic
def record_receipt(*, actor, lot, reason, **values):
    """Add receipt details to a quarantined lot that has none (received before they were kept)."""
    require_role(actor, "analyst")
    lot = _lock_quarantined(actor, lot, "Only quarantined lots accept receipt details.")
    if LotReceipt.objects.filter(lot=lot).exists():
        raise ValidationError("Receipt details are already recorded; correct them instead.")
    receipt = _add_receipt(actor=actor, lot=lot, reason=reason, values=values)
    lot.revision += 1
    lot.save(update_fields=["revision"])
    return receipt


@transaction.atomic
def correct_receipt(*, actor, receipt, reason, **values):
    """Replace the current receipt details with a linked record; the original is kept."""
    require_role(actor, "analyst")
    lot = _lock_quarantined(actor, receipt.lot, "Only quarantined lots accept receipt corrections.")
    current = current_receipt(lot)
    if current is None or current.pk != receipt.pk:
        raise ValidationError(RECEIPT_STALE)
    corrected = _add_receipt(actor=actor, lot=lot, reason=reason, values=values, corrects=current)
    lot.revision += 1
    lot.save(update_fields=["revision"])
    return corrected


@transaction.atomic
def add_sample(*, actor, lot, reference, collected_at, reason):
    require_role(actor, "analyst")
    # Signing locks the actor before the lot; serialize here before taking any record lock.
    # NO KEY UPDATE stays compatible with deferred foreign-key checks on this account.
    get_user_model().objects.select_for_update(no_key=True).get(pk=actor.pk)
    lot = Lot.objects.select_for_update().get(pk=lot.pk)
    if lot.state != "quarantine":
        raise ValidationError("Only quarantined lots accept new samples.")
    sample = Sample.objects.create(
        lot=lot, reference=reference, collected_at=collected_at, created_by=actor
    )
    lot.revision += 1
    lot.save(update_fields=["revision"])
    record_event(
        actor=actor,
        action="sample.collected",
        obj=sample,
        reason=reason,
        after={"lot": lot.pk, "reference": reference, "collected_at": collected_at.isoformat()},
    )
    return sample


@transaction.atomic
def record_result(*, actor, sample, reason, **values):
    require_role(actor, "analyst")
    lot = Lot.objects.select_for_update().get(pk=sample.lot_id)
    if not settings.DEBUG or lot.qc_assignments.exists():
        raise ValidationError("Record observations through approved native testing requirements.")
    if lot.state != "quarantine":
        raise ValidationError("Only quarantined lots accept results.")
    if values["test_code"] not in effective_rules(lot.rules):
        raise ValidationError("Test is not required by this lot's rule set.")
    result = Result(sample=sample, analyst=actor, **values)
    result.full_clean()
    result.save()
    lot.revision += 1
    lot.save(update_fields=["revision"])
    record_event(
        actor=actor,
        action="result.recorded",
        obj=result,
        reason=reason,
        after={"sample": sample.pk, **{k: str(v) for k, v in values.items()}},
    )
    return result


@sensitive_variables("pin")
def review_result(*, actor, pin, result, expected_revision, reason):
    def apply(locked):
        lot = Lot.objects.select_for_update().get(pk=locked.sample.lot_id)
        if lot.state != "quarantine" or locked.state != "recorded":
            raise ValidationError("This result is not awaiting review.")
        if locked.analyst_id == actor.pk:
            raise ValidationError("You cannot review your own result.")
        if not locked.conforms:
            raise ValidationError("Out-of-specification result: investigation is required.")
        effective_rules(lot.rules)
        locked.state = "reviewed"
        lot.revision += 1
        lot.save(update_fields=["revision"])

    return sign_transition(
        actor=actor,
        pin=pin,
        obj=result,
        expected_revision=expected_revision,
        meaning="reviewed",
        reason=reason,
        permission="reviewer",
        apply=apply,
    )


SELF_DISPOSITION = (
    "You cannot disposition a lot containing your own receipt, sampling or test data."
)


def receipt_author_ids(lot):
    """Everyone who recorded receipt details for the lot, corrected originals included."""
    return set(LotReceipt.objects.filter(lot=lot).values_list("recorded_by_id", flat=True))


def disposition_authors(lot):
    """Everyone who authored the lot's receipt, sampling or test data; none may sign its
    disposition.

    Recorders of receipt details including corrected originals, analytical authors
    (observations including corrected originals, submitters, batch QC, investigations),
    samplers and recorders of every sampling record including corrected originals and
    intermediate corrections, and foundation result analysts. Holding several roles never
    waives this.
    """
    from analytical.gates import lot_author_ids as analytical_author_ids
    from sampling.services import lot_author_ids as sampling_author_ids

    return (
        receipt_author_ids(lot)
        | analytical_author_ids(lot)
        | sampling_author_ids(lot)
        | set(Result.objects.filter(sample__lot=lot).values_list("analyst_id", flat=True))
    )


def disposition_denial(actor, lot):
    """Read-only preflight shown before any PIN is requested; signing repeats it under lock."""
    return SELF_DISPOSITION if actor.pk in disposition_authors(lot) else ""


@sensitive_variables("pin")
def dispose_lot(*, actor, pin, lot, expected_revision, reason):
    def apply(locked):
        if locked.state != "quarantine":
            raise ValidationError("This lot has already been dispositioned.")
        from stability.gates import lot_blockers as hold_blockers

        if problems := hold_blockers(locked):
            raise ValidationError(problems)
        required = set(effective_rules(locked.rules))
        from analytical.gates import lot_blockers, lot_evidence
        from analytical.models import AnalyticalTest
        from sampling.services import current_assignment, current_requirements
        from sampling.services import lot_blockers as sampling_blockers

        assignment = current_assignment(locked)
        native = assignment is not None or AnalyticalTest.objects.filter(lot=locked).exists()
        if native or not settings.DEBUG:
            current_requirements(locked)  # missing or held applicability is a hard stop
            if not locked.samples.exists():
                raise ValidationError("The lot requires a sampled and tested record.")
            problems = sampling_blockers(locked) + lot_blockers(locked)
            if problems:
                raise ValidationError(problems)
            if actor.pk in disposition_authors(locked):
                raise ValidationError(SELF_DISPOSITION)
            if Result.objects.filter(sample__lot=locked).exists():
                raise ValidationError(
                    "Mixed foundation and native evidence requires reconciliation."
                )
            locked.disposition_evidence = {
                "assignment_id": assignment.pk,
                "assignment_hash": assignment.payload_hash,
                "analytical": lot_evidence(locked),
            }
            locked.state = "released"
            return
        samples = list(locked.samples.all())
        if not samples:
            raise ValidationError("The lot requires a sample and reviewed results.")
        if actor.pk in receipt_author_ids(locked):
            raise ValidationError(SELF_DISPOSITION)
        for sample in samples:
            results = list(sample.results.all())
            if not required.issubset({r.test_code for r in results}):
                raise ValidationError("Required tests are missing.")
            if any(r.analyst_id == actor.pk for r in results):
                raise ValidationError(SELF_DISPOSITION)
            if any(r.state != "reviewed" or not r.conforms for r in results):
                raise ValidationError("All results must conform and have independent review.")
        locked.state = "released"

    return sign_transition(
        actor=actor,
        pin=pin,
        obj=lot,
        expected_revision=expected_revision,
        meaning="approved",
        reason=reason,
        permission="quality",
        apply=apply,
    )
