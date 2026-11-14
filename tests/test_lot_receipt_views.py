"""Receipt details through the pages: receiving, the lot record, corrections and search."""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import AuditEvent
from quality.models import Lot, LotReceipt
from quality.services import correct_receipt, current_receipt
from tests.receipts import on_site_receipt, supplier_receipt
from tests.test_lot_receipt import (
    approved_rules,
    legacy_lot,
    receive,
    release,
    staff,
    synthetic_supplier,
)

pytestmark = pytest.mark.django_db(transaction=True)
OTHER_ROLES = ["reviewer", "quality", "auditor", "admin"]


@pytest.fixture
def people(django_user_model):
    return staff(django_user_model)


@pytest.fixture
def rules(people):
    return approved_rules(people)


@pytest.fixture
def supplier(people):
    return synthetic_supplier(people)


def posted(supplier=None, **changes):
    """The receipt part of a submitted form, as text."""
    data = {
        "source": "supplier" if supplier else "on_site",
        "supplier": supplier.pk if supplier else "",
        "supplier_lot": "SUP-LOT-SYN-001" if supplier else "",
        "manufacturer": "",
        "manufacturer_location": "",
        "manufacturer_lot": "",
        "shipment_ref": "DN-SYN-001",
        "received_on": timezone.localdate().isoformat(),
        "quantity": "125.50",
        "quantity_unit": "kg",
        "containers": "5",
        "container_description": "25 kg fibre drums",
        "condition": "acceptable",
        "condition_notes": "",
        "reason": "Synthetic receipt",
    }
    return data | changes


def lot_form(rules, source=None, **changes):
    lot = {"number": "SYN-WEB-001", "material": "Synthetic powder", "rules": rules.pk}
    return posted(source) | lot | changes


def test_new_lot_form_groups_the_receipt_details(client, people, rules, supplier):
    client.force_login(people["analyst"])
    body = client.get(reverse("quality:lot_new")).content.decode()
    for legend in ("Lot", "Source", "Delivery", "Examination on receipt", "Change control"):
        assert f"<legend>{legend}</legend>" in body
    for label in ("Lot number", "Supplier lot number", "Date received", "Number of containers"):
        assert label in body
    assert "sup-syn-001 · Synthetic Ingredients Supply" in body
    assert f'value="{timezone.localdate().isoformat()}"' in body  # Today, in the laboratory zone.


@pytest.mark.parametrize("unstated", ["source", "quantity_unit", "condition"])
def test_source_unit_and_examination_are_stated_not_assumed(
    client, people, rules, supplier, unstated
):
    """The menus open on no choice, so an outcome is never recorded because it came first."""
    client.force_login(people["analyst"])
    url = reverse("quality:lot_new")
    form = client.get(url).context["form"]
    assert form.fields[unstated].choices[0] == ("", "—") and form[unstated].value() is None
    response = client.post(url, lot_form(rules, supplier) | {unstated: ""})
    assert response.status_code == 422
    assert response.context["form"].errors[unstated] == ["This field is required."]
    assert not Lot.objects.exists() and not LotReceipt.objects.exists()


def test_lot_is_received_through_the_form(client, people, rules, supplier):
    client.force_login(people["analyst"])
    response = client.post(reverse("quality:lot_new"), lot_form(rules, supplier))
    lot = Lot.objects.get(number="SYN-WEB-001")
    assert response.status_code == 302
    assert response.url == reverse("quality:lot_detail", args=[lot.pk])
    receipt = current_receipt(lot)
    assert (receipt.supplier, receipt.quantity_text, receipt.containers) == (supplier, "125.5", 5)
    body = client.get(response.url).content.decode()
    assert "Lot received in quarantine." in body
    for shown in (
        "Received from a supplier",
        f'href="{reverse("suppliers:detail", args=[supplier.pk])}"',
        "SUP-LOT-SYN-001",
        "DN-SYN-001",
        "125.5 kg",
        "5 · 25 kg fibre drums",
        "No discrepancy found",
        "Receipt recorded",
        "Correct receipt details",
    ):
        assert shown in body
    assert "Manufacturer</dt><dd>Not stated" in body


def test_refused_form_keeps_entries_and_receives_nothing(
    client,
    people,
    rules,
    supplier,
):
    client.force_login(people["analyst"])
    url = reverse("quality:lot_new")
    cases = [
        (lot_form(rules, supplier, supplier=""), "Select the supplier the lot was received from."),
        (lot_form(rules, supplier_lot="X-1"), "Material made on site has no supplier"),
        (lot_form(rules, condition="discrepancy"), "Describe the discrepancy found on receipt."),
        (lot_form(rules, quantity="0"), "Enter an exact quantity greater than zero."),
        (lot_form(rules, quantity="1.23456"), "no more than 4 decimal places"),
        (lot_form(rules, containers="0"), "greater than or equal to 1"),
        (lot_form(rules, received_on="2999-01-01"), "The date received cannot be in the future."),
        (lot_form(rules, reason=""), "This field is required."),
    ]
    for data, message in cases:
        response = client.post(url, data)
        body = response.content.decode()
        assert response.status_code == 422, message
        assert message in body, message
        assert 'value="SYN-WEB-001"' in body  # Entries are kept.
    assert not Lot.objects.exists() and not LotReceipt.objects.exists()
    assert not AuditEvent.objects.filter(action__startswith="lot.").exists()

    assert client.post(url, lot_form(rules)).status_code == 302
    duplicate = client.post(url, lot_form(rules))
    assert duplicate.status_code == 422
    assert "This lot number already exists." in duplicate.content.decode()
    assert Lot.objects.count() == 1


def test_concurrent_duplicate_lot_number_is_a_conflict(
    client,
    people,
    rules,
    monkeypatch,
):
    from catalog.tests.factories import commit_first_on_save

    def competitor():
        Lot.objects.create(
            number="SYN-WEB-001",
            material="Other request",
            rules=rules,
            created_by=people["analyst2"],
        )

    commit_first_on_save(monkeypatch, Lot, competitor)
    client.force_login(people["analyst"])
    response = client.post(reverse("quality:lot_new"), lot_form(rules))
    assert response.status_code == 422
    assert "Another request saved a conflicting record" in response.content.decode()
    assert Lot.objects.get().material == "Other request" and not LotReceipt.objects.exists()


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_read_the_receipt_and_cannot_change_it(
    client,
    people,
    rules,
    supplier,
    role,
):
    lot = receive(people, rules, supplier_receipt(supplier))
    earlier = legacy_lot(people, rules)
    client.force_login(people[role])
    body = client.get(reverse("quality:lot_detail", args=[lot.pk])).content.decode()
    assert "SUP-LOT-SYN-001" in body and "Correct receipt details" not in body
    body = client.get(reverse("quality:lot_detail", args=[earlier.pk])).content.decode()
    assert "Receipt details are not recorded" in body and "Record receipt details" not in body
    for name, target in (
        ("quality:lot_new", None),
        ("quality:receipt_correct", lot),
        ("quality:receipt_new", earlier),
    ):
        url = reverse(name, args=[target.pk] if target else [])
        assert client.get(url).status_code == 403
        assert client.post(url, posted(supplier)).status_code == 403
    assert LotReceipt.objects.count() == 1 and Lot.objects.count() == 2


def test_receipt_details_are_recorded_for_an_earlier_lot(
    client,
    people,
    rules,
    supplier,
):
    lot = legacy_lot(people, rules)
    client.force_login(people["analyst"])
    detail = reverse("quality:lot_detail", args=[lot.pk])
    url = reverse("quality:receipt_new", args=[lot.pk])
    body = client.get(detail).content.decode()
    assert "Receipt details are not recorded" in body and f'href="{url}"' in body
    page = client.get(url).content.decode()
    assert "Record receipt details" in page and "SYN-LEGACY-001" in page
    refused = client.post(url, posted(supplier, shipment_ref=""))
    assert refused.status_code == 422 and not LotReceipt.objects.exists()
    response = client.post(url, posted(supplier))
    assert (response.status_code, response.url) == (302, detail)
    lot.refresh_from_db()
    assert lot.revision == 2 and current_receipt(lot).supplier == supplier
    # Once recorded, the page sends the user to the lot record instead of a second form.
    again = client.get(url, follow=True)
    assert again.redirect_chain == [(detail, 302)]
    assert "Receipt details are already recorded; correct them instead." in again.content.decode()
    assert client.post(url, posted(supplier)).status_code == 302
    assert lot.receipts.count() == 1


def test_receipt_is_corrected_through_the_form(
    client,
    people,
    rules,
    supplier,
):
    lot = receive(people, rules, supplier_receipt(supplier))
    original = current_receipt(lot)
    client.force_login(people["analyst2"])
    detail = reverse("quality:lot_detail", args=[lot.pk])
    url = reverse("quality:receipt_correct", args=[lot.pk])
    page = client.get(url).content.decode()
    # The form opens with the current details and names the record it replaces.
    assert 'value="SUP-LOT-SYN-001"' in page and 'value="25"' in page
    assert f'name="receipt" value="{original.pk}"' in page
    assert "Reason for correction" in page

    same = posted(
        supplier, quantity="25", containers="1", container_description="Synthetic 25 kg drum"
    )
    unchanged = client.post(url, same | {"receipt": original.pk, "reason": "Nothing"})
    assert unchanged.status_code == 422
    assert "The correction changes nothing." in unchanged.content.decode()

    change = same | {
        "receipt": original.pk,
        "supplier_lot": "SUP-LOT-SYN-002",
        "condition": "discrepancy",
        "condition_notes": "Synthetic drum 2 has a torn outer label.",
        "reason": "Supplier lot misread from the drum label",
    }
    response = client.post(url, change)
    assert (response.status_code, response.url) == (302, detail)
    lot.refresh_from_db()
    corrected = current_receipt(lot)
    assert lot.revision == 2 and corrected.corrects == original
    assert corrected.recorded_by == people["analyst2"]
    body = client.get(detail).content.decode()
    assert "Receipt details corrected; the original is kept." in body
    assert "Receipt details corrected</span>" in body
    assert '<del class="vr-prior">SUP-LOT-SYN-001</del>' in body and "SUP-LOT-SYN-002" in body
    assert '<del class="vr-prior">No discrepancy found</del>' in body
    assert "Synthetic drum 2 has a torn outer label." in body
    assert "A discrepancy does not hold the lot by itself." in body
    assert "Supplier lot misread from the drum label" in body

    # A page opened before that correction still names the replaced record.
    stale = client.post(url, change | {"supplier_lot": "SUP-LOT-SYN-003"})
    assert stale.status_code == 422
    assert "The receipt details changed. Reload and review them" in stale.content.decode()
    assert lot.receipts.count() == 2


def test_correction_form_opens_on_the_current_details_exactly(client, people, rules, supplier):
    """Submitting the form as it opened changes nothing: every detail round-trips."""
    lot = receive(
        people,
        rules,
        supplier_receipt(
            supplier,
            manufacturer="Synthetic Maker",
            manufacturer_location="Testville, Exampleland",
            manufacturer_lot="MFR-77",
            quantity=Decimal("125.5000"),
            quantity_unit="g",
            containers=5,
            condition="discrepancy",
            condition_notes="Synthetic drum 2 has a torn outer label.",
        ),
    )
    client.force_login(people["analyst"])
    url = reverse("quality:receipt_correct", args=[lot.pk])
    form = client.get(url).context["form"]
    opened = {name: form[name].value() for name in form.fields if name != "reason"}
    assert opened["supplier"] == supplier.pk and opened["quantity"] == "125.5"
    assert (opened["quantity_unit"], opened["condition"]) == ("g", "discrepancy")
    opened["received_on"] = opened["received_on"].isoformat()
    response = client.post(url, opened | {"reason": "Opened and submitted unchanged"})
    assert response.status_code == 422
    assert "The correction changes nothing." in response.content.decode()
    assert lot.receipts.count() == 1


def test_correction_names_the_record_it_replaces(client, people, rules, supplier):
    lot = receive(people, rules, supplier_receipt(supplier))
    other = receive(people, rules, supplier_receipt(supplier), number="SYN-R-002")
    client.force_login(people["analyst"])
    url = reverse("quality:receipt_correct", args=[lot.pk])
    change = posted(supplier, containers="9", reason="Recount")
    # Another lot's record, a record that does not exist and no record at all are refused.
    for receipt, message in (
        (current_receipt(other).pk, "The receipt details changed. Reload and review them"),
        (987654, "The receipt details changed. Reload and review them"),
        (None, "This field is required."),
    ):
        data = change | ({"receipt": receipt} if receipt else {})
        response = client.post(url, data)
        assert response.status_code == 422 and message in response.content.decode()
    assert LotReceipt.objects.count() == 2
    assert client.post(url, change | {"receipt": current_receipt(lot).pk}).status_code == 302
    assert current_receipt(lot).containers == 9 and other.receipts.count() == 1


def test_receipt_pages_close_when_the_lot_is_released(
    client,
    people,
    rules,
    supplier,
    settings,
):
    lot = receive(people, rules, supplier_receipt(supplier))
    earlier = legacy_lot(people, rules)
    release(people, lot, settings)
    release(people, earlier, settings)
    client.force_login(people["analyst"])
    for name, target, message in (
        ("quality:receipt_correct", lot, "Only quarantined lots accept receipt corrections."),
        ("quality:receipt_new", earlier, "Only quarantined lots accept receipt details."),
    ):
        detail = reverse("quality:lot_detail", args=[target.pk])
        response = client.post(
            reverse(name, args=[target.pk]),
            posted(supplier, receipt=current_receipt(lot).pk, containers="9"),
            follow=True,
        )
        body = response.content.decode()
        assert response.redirect_chain == [(detail, 302)] and message in body
        assert "Correct receipt details" not in body and "Record receipt details" not in body
    assert LotReceipt.objects.count() == 1
    body = client.get(reverse("quality:lot_detail", args=[earlier.pk])).content.decode()
    assert "Receipt details are not recorded" in body and "An analyst can record" not in body


def test_correction_page_needs_receipt_details_to_correct(client, people, rules):
    lot = legacy_lot(people, rules)
    client.force_login(people["analyst"])
    response = client.get(reverse("quality:receipt_correct", args=[lot.pk]), follow=True)
    assert "This lot has no receipt details to correct." in response.content.decode()


def test_lot_list_shows_and_searches_the_current_receipt(
    client,
    people,
    rules,
    supplier,
):
    lot = receive(
        people,
        rules,
        supplier_receipt(supplier, manufacturer="Synthetic Maker", manufacturer_lot="MFR-77"),
    )
    receive(people, rules, on_site_receipt(), number="SYN-R-002")
    legacy_lot(people, rules)
    client.force_login(people["auditor"])
    url = reverse("quality:lot_list")
    body = client.get(url).content.decode()
    assert "Synthetic Ingredients Supply" in body and "SUP-LOT-SYN-001" in body
    assert "Made on site" in body and "Receipt not recorded" in body

    def found(query):
        page = client.get(url, {"q": query}).content.decode()
        return [number for number in ("SYN-R-001", "SYN-R-002", "SYN-LEGACY-001") if number in page]

    assert found("syn-r-00") == ["SYN-R-001", "SYN-R-002"]
    assert found("sup-lot-syn") == ["SYN-R-001"]
    assert found("mfr-77") == ["SYN-R-001"]
    correct_receipt(
        actor=people["analyst"],
        receipt=current_receipt(lot),
        reason="Supplier lot misread",
        **supplier_receipt(supplier, supplier_lot="CORRECTED-9"),
    )
    # Search follows the current details, not the record a correction replaced.
    assert found("sup-lot-syn") == [] and found("mfr-77") == []
    assert found("corrected-9") == ["SYN-R-001"]
    empty = client.get(url, {"q": "nothing-matches"}).content.decode()
    assert "No material lots match these filters" in empty
    assert "supplier and manufacturer lot numbers" in empty
