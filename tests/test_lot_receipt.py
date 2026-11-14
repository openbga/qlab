"""Receipt details of a lot: required at receipt, append-only, corrected by linked records."""

import datetime
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.urls import reverse
from django.utils import timezone

from core.models import AuditEvent, ElectronicSignature, RuleSet
from core.services import set_pin
from quality import services
from quality.models import Lot, LotReceipt
from quality.services import (
    add_sample,
    correct_receipt,
    current_receipt,
    dispose_lot,
    receive_lot,
    record_receipt,
    record_result,
    review_result,
)
from suppliers.services import create_supplier
from tests.receipts import on_site_receipt, supplier_receipt

pytestmark = pytest.mark.django_db(transaction=True)
PIN = "12345678"
PASSWORD = "test-password-2026"


def staff(django_user_model):
    found = {}
    for name, roles in {
        "analyst": ["analyst"],
        "analyst2": ["analyst"],
        "reviewer": ["reviewer"],
        "quality": ["quality"],
        "auditor": ["auditor"],
        "admin": ["admin"],
        "receiver": ["analyst", "quality"],
    }.items():
        user = django_user_model.objects.create_user(name, password=PASSWORD)
        for role in roles:
            user.groups.add(Group.objects.get_or_create(name=role)[0])
        set_pin(actor=user, pin=PIN, password=PASSWORD)
        found[name] = user
    return found


def approved_rules(people):
    return RuleSet.objects.create(
        code="synthetic",
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


def synthetic_supplier(people):
    return create_supplier(
        actor=people["quality"],
        code="sup-syn-001",
        name="Synthetic Ingredients Supply",
        location="Sampletown, Exampleland",
        reason="Synthetic master data",
    )


@pytest.fixture
def people(django_user_model):
    return staff(django_user_model)


@pytest.fixture
def rules(people):
    return approved_rules(people)


@pytest.fixture
def supplier(people):
    return synthetic_supplier(people)


def receive(people, rules, receipt, number="SYN-R-001", actor="analyst"):
    return receive_lot(
        actor=people[actor],
        number=number,
        material="Synthetic powder",
        rules=rules,
        reason="Synthetic receipt",
        receipt=receipt,
    )


def legacy_lot(people, rules, number="SYN-LEGACY-001"):
    """A lot received before receipt details were kept: it has no receipt record."""
    return Lot.objects.create(
        number=number, material="Synthetic powder", rules=rules, created_by=people["analyst"]
    )


def with_reviewed_result(people, lot, settings):
    """A sampled lot with a reviewed conforming result, on the development-only manual path
    (it needs no catalog fixtures). Returns the lot as the quality user would open it."""
    settings.DEBUG = True
    sample = add_sample(
        actor=people["analyst2"],
        lot=lot,
        reference=f"{lot.number}-S1",
        collected_at=timezone.now(),
        reason="Synthetic sample",
    )
    result = record_result(
        actor=people["analyst2"],
        sample=sample,
        reason="Synthetic measurement",
        test_code="identity",
        value=Decimal("1.0"),
        unit="ratio",
        lower_limit=Decimal("0.9"),
        upper_limit=Decimal("1.1"),
    )
    review_result(
        actor=people["reviewer"], pin=PIN, result=result, expected_revision=1, reason="Checked"
    )
    lot.refresh_from_db()
    return lot


def release(people, lot, settings):
    lot = with_reviewed_result(people, lot, settings)
    return dispose_lot(
        actor=people["quality"],
        pin=PIN,
        lot=lot,
        expected_revision=lot.revision,
        reason="Synthetic disposition",
    )


# Receiving -------------------------------------------------------------------------------------


def test_lot_is_received_with_its_receipt_details(people, rules, supplier):
    details = supplier_receipt(
        supplier,
        manufacturer="Synthetic Maker",
        manufacturer_location="Testville, Exampleland",
        manufacturer_lot="MFR-SYN-77",
        quantity=Decimal("125.50"),
        containers=5,
        container_description="  25 kg fibre drums  ",
    )
    lot = receive(people, rules, details)
    receipt = current_receipt(lot)
    assert lot.revision == 1 and lot.state == "quarantine"
    assert (receipt.supplier, receipt.supplier_lot) == (supplier, "SUP-LOT-SYN-001")
    assert (receipt.quantity, receipt.quantity_text) == (Decimal("125.5"), "125.5")
    assert receipt.container_description == "25 kg fibre drums"  # Surrounding space is not kept.
    assert (receipt.recorded_by, receipt.corrects, receipt.reason) == (
        people["analyst"],
        None,
        "Synthetic receipt",
    )
    events = list(AuditEvent.objects.filter(action__startswith="lot.").order_by("occurred_at"))
    assert [event.action for event in events] == ["lot.received", "lot.receipt_recorded"]
    recorded = events[1]
    assert (recorded.object_type, recorded.object_id) == ("quality.lotreceipt", str(receipt.pk))
    assert recorded.before == {}
    assert recorded.after == {
        "lot": lot.pk,
        "source": "supplier",
        "supplier": "sup-syn-001",
        "supplier_lot": "SUP-LOT-SYN-001",
        "manufacturer": "Synthetic Maker",
        "manufacturer_location": "Testville, Exampleland",
        "manufacturer_lot": "MFR-SYN-77",
        "shipment_ref": "DN-SYN-001",
        "received_on": timezone.localdate().isoformat(),
        "quantity": "125.5",
        "quantity_unit": "kg",
        "containers": 5,
        "container_description": "25 kg fibre drums",
        "condition": "acceptable",
        "condition_notes": "",
        "corrects": None,
    }


def test_material_made_on_site_needs_no_supplier(people, rules):
    lot = receive(people, rules, on_site_receipt())
    receipt = current_receipt(lot)
    assert (receipt.source, receipt.supplier, receipt.supplier_lot) == ("on_site", None, "")


INVALID = {
    "supplier source without a supplier": ({"source": "supplier"}, "supplier", "Select the"),
    "on site with a supplier lot": ({"supplier_lot": "X-1"}, "source", "made on site"),
    "on site with a manufacturer": ({"manufacturer": "Synthetic Maker"}, "source", "made on site"),
    "unknown source": ({"source": "elsewhere"}, "source", "where the lot came from"),
    "future date": (
        {"received_on": datetime.date(2999, 1, 1)},
        "received_on",
        "cannot be in the future",
    ),
    "date and time": ({"received_on": timezone.now()}, "received_on", "Enter the date"),
    "no date": ({"received_on": None}, "received_on", "Enter the date"),
    "zero quantity": ({"quantity": Decimal("0")}, "quantity", "greater than zero"),
    "negative quantity": ({"quantity": Decimal("-1")}, "quantity", "greater than zero"),
    "float quantity": ({"quantity": 25.0}, "quantity", "exact quantity"),
    "undefined quantity": ({"quantity": Decimal("NaN")}, "quantity", "exact quantity"),
    "too many decimals": ({"quantity": Decimal("1.00001")}, "quantity", "4 decimal places"),
    "unknown unit": ({"quantity_unit": "lb"}, "quantity_unit", "not a valid choice"),
    "no containers": ({"containers": 0}, "containers", "at least one"),
    "containers not a count": ({"containers": True}, "containers", "at least one"),
    "no document": ({"shipment_ref": "  "}, "shipment_ref", "delivery or batch document"),
    "no container description": (
        {"container_description": ""},
        "container_description",
        "Describe the containers",
    ),
    "discrepancy without notes": (
        {"condition": "discrepancy"},
        "condition_notes",
        "Describe the discrepancy",
    ),
    "unknown condition": ({"condition": "fine"}, "condition", "not a valid choice"),
}


@pytest.mark.parametrize("case", INVALID)
def test_invalid_receipt_details_receive_nothing(people, rules, case):
    changes, field, message = INVALID[case]
    with pytest.raises(ValidationError) as refused:
        receive(people, rules, on_site_receipt(**changes))
    assert message in " ".join(refused.value.message_dict[field])
    # The lot and its receipt details are received together or not at all.
    assert not Lot.objects.exists() and not LotReceipt.objects.exists()
    assert not AuditEvent.objects.filter(action__startswith="lot.").exists()


def test_manufacturer_details_need_the_manufacturer_named(people, rules, supplier):
    for changes in ({"manufacturer_lot": "MFR-1"}, {"manufacturer_location": "Testville"}):
        with pytest.raises(ValidationError) as refused:
            receive(people, rules, supplier_receipt(supplier, **changes))
        assert "Name the manufacturer" in refused.value.message_dict["manufacturer"][0]
    assert not Lot.objects.exists()


@pytest.mark.parametrize("shape", ["missing", "extra", "not a mapping"])
def test_receipt_details_are_complete_or_refused(people, rules, shape):
    details = on_site_receipt()
    if shape == "missing":
        del details["condition"]
    elif shape == "extra":
        details["expiry"] = "2030-01-01"
    else:
        details = None
    with pytest.raises(ValidationError, match="incomplete"):
        receive(people, rules, details)
    assert not Lot.objects.exists()


@pytest.mark.parametrize("actor", ["reviewer", "quality", "auditor", "admin"])
def test_only_analysts_receive_lots(people, rules, actor):
    with pytest.raises(PermissionDenied):
        receive(people, rules, on_site_receipt(), actor=actor)
    assert not Lot.objects.exists() and not LotReceipt.objects.exists()


def test_receipt_needs_a_reason(people, rules):
    with pytest.raises(ValidationError, match="reason is required"):
        receive_lot(
            actor=people["analyst"],
            number="SYN-R-001",
            material="Synthetic powder",
            rules=rules,
            reason="  ",
            receipt=on_site_receipt(),
        )
    assert not Lot.objects.exists()


# Lots received before receipt details were kept ------------------------------------------------


def test_receipt_details_are_added_to_an_earlier_quarantined_lot(people, rules, supplier):
    lot = legacy_lot(people, rules)
    assert current_receipt(lot) is None
    receipt = record_receipt(
        actor=people["analyst2"],
        lot=lot,
        reason="Recorded from the synthetic delivery note",
        **supplier_receipt(supplier),
    )
    lot.refresh_from_db()
    assert lot.revision == 2 and current_receipt(lot) == receipt
    event = AuditEvent.objects.get(action="lot.receipt_recorded")
    assert event.actor == people["analyst2"] and event.after["supplier"] == "sup-syn-001"
    with pytest.raises(ValidationError, match="already recorded; correct them instead"):
        record_receipt(
            actor=people["analyst"], lot=lot, reason="Again", **supplier_receipt(supplier)
        )
    lot.refresh_from_db()
    assert lot.revision == 2 and lot.receipts.count() == 1


def test_receipt_details_are_not_added_after_release_or_by_other_roles(people, rules, settings):
    lot = legacy_lot(people, rules)
    for actor in ("reviewer", "quality", "auditor", "admin"):
        with pytest.raises(PermissionDenied):
            record_receipt(actor=people[actor], lot=lot, reason="Synthetic", **on_site_receipt())
    released = release(people, lot, settings)
    with pytest.raises(ValidationError, match="Only quarantined lots accept receipt details"):
        record_receipt(
            actor=people["analyst"], lot=released, reason="Synthetic", **on_site_receipt()
        )
    assert not LotReceipt.objects.exists()


# Corrections -----------------------------------------------------------------------------------


def test_correction_adds_a_linked_record_and_keeps_the_original(people, rules, supplier):
    lot = receive(people, rules, supplier_receipt(supplier))
    original = current_receipt(lot)
    corrected = correct_receipt(
        actor=people["analyst2"],
        receipt=original,
        reason="Supplier lot misread from the drum label",
        **supplier_receipt(supplier, supplier_lot="SUP-LOT-SYN-002", containers=2),
    )
    lot.refresh_from_db()
    original.refresh_from_db()
    assert lot.revision == 2
    assert (original.supplier_lot, original.containers) == ("SUP-LOT-SYN-001", 1)
    assert (corrected.corrects, corrected.recorded_by) == (original, people["analyst2"])
    assert current_receipt(lot) == corrected and lot.receipts.count() == 2
    event = AuditEvent.objects.get(action="lot.receipt_corrected")
    assert (event.object_id, event.actor) == (str(corrected.pk), people["analyst2"])
    assert event.before["supplier_lot"] == "SUP-LOT-SYN-001" and event.before["corrects"] is None
    assert event.after["supplier_lot"] == "SUP-LOT-SYN-002"
    assert event.after["corrects"] == original.pk
    assert event.reason == "Supplier lot misread from the drum label"


def test_correction_can_change_the_source(people, rules, supplier):
    lot = receive(people, rules, supplier_receipt(supplier))
    corrected = correct_receipt(
        actor=people["analyst"],
        receipt=current_receipt(lot),
        reason="Made on site, not purchased",
        **on_site_receipt(),
    )
    assert (corrected.source, corrected.supplier) == ("on_site", None)


def test_refused_corrections_change_nothing(people, rules, supplier, settings):
    lot = receive(people, rules, supplier_receipt(supplier))
    original = current_receipt(lot)
    change = supplier_receipt(supplier, containers=3)
    with pytest.raises(ValidationError, match="changes nothing"):
        correct_receipt(
            actor=people["analyst"],
            receipt=original,
            reason="Synthetic",
            # The same details with insignificant differences in spacing and decimal padding.
            **supplier_receipt(supplier, quantity=Decimal("25.0000"), shipment_ref=" DN-SYN-001 "),
        )
    with pytest.raises(ValidationError, match="reason is required"):
        correct_receipt(actor=people["analyst"], receipt=original, reason="", **change)
    with pytest.raises(ValidationError) as invalid:
        correct_receipt(
            actor=people["analyst"],
            receipt=original,
            reason="Synthetic",
            **supplier_receipt(supplier, condition="discrepancy"),
        )
    assert "condition_notes" in invalid.value.message_dict
    for actor in ("reviewer", "quality", "auditor", "admin"):
        with pytest.raises(PermissionDenied):
            correct_receipt(actor=people[actor], receipt=original, reason="Synthetic", **change)
    lot.refresh_from_db()
    assert lot.revision == 1 and lot.receipts.count() == 1
    assert not AuditEvent.objects.filter(action="lot.receipt_corrected").exists()

    corrected = correct_receipt(
        actor=people["analyst"], receipt=original, reason="Recount", **change
    )
    # A page that still shows the corrected original cannot replace the newer details.
    with pytest.raises(ValidationError, match="receipt details changed"):
        correct_receipt(
            actor=people["analyst2"],
            receipt=original,
            reason="Stale",
            **supplier_receipt(supplier, containers=9),
        )
    released = release(people, lot, settings)
    with pytest.raises(ValidationError, match="Only quarantined lots accept receipt corrections"):
        correct_receipt(
            actor=people["analyst"],
            receipt=corrected,
            reason="After release",
            **supplier_receipt(supplier, containers=9),
        )
    assert current_receipt(released) == corrected and released.receipts.count() == 2


def test_simultaneous_corrections_of_one_record_cannot_both_apply(
    people, rules, supplier, monkeypatch
):
    from laboratory.tests.helpers import run_interleaved

    lot = receive(people, rules, supplier_receipt(supplier))
    original = current_receipt(lot)

    def correct(actor, containers):
        return lambda: correct_receipt(
            actor=people[actor],
            receipt=original,
            reason=f"Recount by {actor}",
            **supplier_receipt(supplier, containers=containers),
        )

    outcome = run_interleaved(
        monkeypatch, services, "record_event", correct("analyst", 2), correct("analyst2", 3)
    )
    assert isinstance(outcome["first"], LotReceipt)
    assert isinstance(outcome["second"], ValidationError)
    assert "receipt details changed" in outcome["second"].messages[0]
    lot.refresh_from_db()
    assert lot.revision == 2 and lot.receipts.count() == 2
    assert current_receipt(lot).containers == 2


# Database guards -------------------------------------------------------------------------------


def test_database_refuses_changes_outside_the_services(people, rules, supplier, settings):
    lot = receive(people, rules, supplier_receipt(supplier))
    other = receive(people, rules, on_site_receipt(), number="SYN-R-002")
    receipt = current_receipt(lot)
    values = {
        name: getattr(receipt, name) for name in services.RECEIPT_FIELDS if name != "supplier"
    } | {"supplier": supplier, "recorded_by": people["analyst"], "reason": "Direct write"}
    refused = [
        lambda: LotReceipt.objects.filter(pk=receipt.pk).update(supplier_lot="CHANGED"),
        lambda: LotReceipt.objects.filter(pk=receipt.pk).delete(),
        # A second original for one lot, and a correction that crosses lots.
        lambda: LotReceipt.objects.create(lot=lot, **values),
        lambda: LotReceipt.objects.create(lot=other, corrects=receipt, **values),
        # Shapes the service refuses that the row constraints can state. An unknown unit and
        # a future date are refused by the service alone.
        lambda: LotReceipt.objects.create(lot=lot, corrects=receipt, **values | {"quantity": 0}),
        lambda: LotReceipt.objects.create(lot=lot, corrects=receipt, **values | {"containers": 0}),
        lambda: LotReceipt.objects.create(
            lot=lot, corrects=receipt, **values | {"source": "on_site"}
        ),
        lambda: LotReceipt.objects.create(lot=lot, corrects=receipt, **values | {"supplier": None}),
        lambda: LotReceipt.objects.create(
            lot=lot, corrects=receipt, **values | {"manufacturer_lot": "MFR-1"}
        ),
        lambda: LotReceipt.objects.create(
            lot=lot, corrects=receipt, **values | {"condition": "discrepancy"}
        ),
        lambda: LotReceipt.objects.create(
            lot=lot,
            corrects=receipt,
            **values | {"condition": "fine", "condition_notes": "Synthetic"},
        ),
        lambda: LotReceipt.objects.create(
            lot=lot, corrects=receipt, **values | {"shipment_ref": ""}
        ),
        lambda: LotReceipt.objects.create(
            lot=lot, corrects=receipt, **values | {"container_description": ""}
        ),
        lambda: LotReceipt.objects.create(lot=lot, corrects=receipt, **values | {"reason": ""}),
    ]
    for action in refused:
        with pytest.raises(DatabaseError), transaction.atomic():
            action()
    release(people, lot, settings)
    with pytest.raises(DatabaseError, match="only while the lot is in quarantine"):
        with transaction.atomic():
            LotReceipt.objects.create(lot=lot, corrects=receipt, **values | {"containers": 4})
    assert LotReceipt.objects.filter(lot=lot).count() == 1
    # The row itself is accepted while the lot is in quarantine: each refusal above is its own.
    with transaction.atomic():
        LotReceipt.objects.create(
            lot=other, corrects=current_receipt(other), **values | {"source": "supplier"}
        )
    assert current_receipt(other).supplier == supplier


def test_database_guard_waits_for_a_release_in_progress(people, rules, settings, monkeypatch):
    """A row written beside a disposition that has not committed yet is still refused."""
    import core.services as signing
    from laboratory.tests.helpers import run_interleaved

    lot = with_reviewed_result(people, receive(people, rules, on_site_receipt()), settings)
    receipt = current_receipt(lot)
    values = {name: getattr(receipt, name) for name in services.RECEIPT_FIELDS} | {
        "containers": 7,
        "recorded_by": people["analyst"],
        "reason": "Direct write beside a release",
    }

    def release():
        return dispose_lot(
            actor=people["quality"],
            pin=PIN,
            lot=lot,
            expected_revision=lot.revision,
            reason="Synthetic disposition",
        )

    def direct_write():
        return LotReceipt.objects.create(lot=lot, corrects=receipt, **values)

    # The signing transaction holds the lot when it writes its audit event.
    outcome = run_interleaved(monkeypatch, signing, "record_event", release, direct_write)
    assert outcome["first"].state == "released"
    assert isinstance(outcome["second"], DatabaseError)
    assert "only while the lot is in quarantine" in str(outcome["second"])
    assert LotReceipt.objects.filter(lot=lot).count() == 1


def test_correction_and_disposition_cannot_both_apply(people, rules, settings, monkeypatch):
    """Whichever takes the lot first wins; the other is refused, never applied on top."""
    import core.services as signing
    from laboratory.tests.helpers import run_interleaved

    lot = with_reviewed_result(people, receive(people, rules, on_site_receipt()), settings)

    def release(target):
        return lambda: dispose_lot(
            actor=people["quality"],
            pin=PIN,
            lot=target,
            expected_revision=target.revision,
            reason="Synthetic disposition",
        )

    def correct(target):
        return lambda: correct_receipt(
            actor=people["analyst"],
            receipt=current_receipt(target),
            reason="Recount",
            **on_site_receipt(containers=2),
        )

    # The correction holds the lot first: the disposition signs a revision that has moved on.
    shown = lot.revision
    outcome = run_interleaved(monkeypatch, services, "record_event", correct(lot), release(lot))
    assert isinstance(outcome["first"], LotReceipt)
    assert "Record changed" in outcome["second"].messages[0]
    lot.refresh_from_db()
    assert (lot.state, lot.revision, lot.receipts.count()) == ("quarantine", shown + 1, 2)
    assert not ElectronicSignature.objects.filter(object_type="quality.lot").exists()

    # The disposition holds the lot first: the correction finds it released.
    other = with_reviewed_result(
        people, receive(people, rules, on_site_receipt(), number="SYN-R-002"), settings
    )
    outcome = run_interleaved(monkeypatch, signing, "record_event", release(other), correct(other))
    assert outcome["first"].state == "released"
    assert "Only quarantined lots accept receipt corrections" in outcome["second"].messages[0]
    assert other.receipts.count() == 1


def test_simultaneous_first_records_for_an_earlier_lot_keep_one(people, rules, monkeypatch):
    from laboratory.tests.helpers import run_interleaved

    lot = legacy_lot(people, rules)

    def record(actor):
        return lambda: record_receipt(
            actor=people[actor], lot=lot, reason=f"Recorded by {actor}", **on_site_receipt()
        )

    outcome = run_interleaved(
        monkeypatch, services, "record_event", record("analyst"), record("analyst2")
    )
    assert isinstance(outcome["first"], LotReceipt)
    assert "already recorded; correct them instead" in outcome["second"].messages[0]
    lot.refresh_from_db()
    assert (lot.revision, lot.receipts.count()) == (2, 1)


# Disposition -----------------------------------------------------------------------------------


def test_correction_makes_an_open_disposition_page_stale(people, rules, supplier, settings):
    lot = receive(people, rules, supplier_receipt(supplier))
    lot = with_reviewed_result(people, lot, settings)
    shown = lot.revision  # The revision the quality user's signing page was opened with.
    correct_receipt(
        actor=people["analyst2"],
        receipt=current_receipt(lot),
        reason="Recount",
        **supplier_receipt(supplier, containers=2),
    )
    with pytest.raises(ValidationError, match="Record changed"):
        dispose_lot(
            actor=people["quality"], pin=PIN, lot=lot, expected_revision=shown, reason="Stale"
        )
    lot.refresh_from_db()
    assert lot.state == "quarantine"
    assert not ElectronicSignature.objects.filter(object_type="quality.lot").exists()
    assert (
        dispose_lot(
            actor=people["quality"],
            pin=PIN,
            lot=lot,
            expected_revision=lot.revision,
            reason="Reviewed the corrected receipt",
        ).state
        == "released"
    )


@pytest.mark.parametrize("authored", ["original", "correction"])
def test_receipt_author_cannot_sign_the_disposition(people, rules, settings, client, authored):
    receiver = people["receiver"]  # Holds the quality role as well; that never waives this.
    lot = receive(
        people, rules, on_site_receipt(), actor="receiver" if authored == "original" else "analyst"
    )
    if authored == "correction":
        correct_receipt(
            actor=receiver,
            receipt=current_receipt(lot),
            reason="Recount",
            **on_site_receipt(containers=2),
        )
    lot = with_reviewed_result(people, lot, settings)
    assert receiver.pk in services.disposition_authors(lot)
    client.force_login(receiver)
    page = client.get(reverse("quality:disposition", args=[lot.pk]))
    assert page.status_code == 403
    assert b"own receipt, sampling or test data" in page.content
    assert b'name="pin"' not in page.content  # Explained before any PIN is requested.
    with pytest.raises(ValidationError, match="own receipt, sampling or test data"):
        dispose_lot(
            actor=receiver, pin=PIN, lot=lot, expected_revision=lot.revision, reason="Own lot"
        )
    lot.refresh_from_db()
    assert lot.state == "quarantine"
    assert not ElectronicSignature.objects.filter(object_type="quality.lot").exists()
    assert (
        dispose_lot(
            actor=people["quality"],
            pin=PIN,
            lot=lot,
            expected_revision=lot.revision,
            reason="Independent disposition",
        ).state
        == "released"
    )


def test_received_date_is_the_laboratory_date_not_utc(people, rules, settings, monkeypatch):
    """Early in the laboratory's day, while UTC is still on the previous date, today's date
    is not in the future and tomorrow's is."""
    settings.TIME_ZONE = "Pacific/Auckland"
    midday_utc = timezone.now().replace(hour=12, minute=30, second=0, microsecond=0)
    monkeypatch.setattr(timezone, "now", lambda: midday_utc)
    with timezone.override("Pacific/Auckland"):
        today = timezone.localdate()
        assert today == midday_utc.date() + timedelta(days=1)  # Auckland is 12 or 13 hours on.
        lot = receive(people, rules, on_site_receipt(received_on=today))
        assert current_receipt(lot).received_on == today
        with pytest.raises(ValidationError, match="cannot be in the future"):
            receive(
                people,
                rules,
                on_site_receipt(received_on=today + timedelta(days=1)),
                number="SYN-R-002",
            )
