"""The supplier register: who may add to it, who may read it and what it shows."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.urls import reverse

from core.models import AuditEvent
from quality.models import Lot
from quality.services import correct_receipt, current_receipt, receive_lot
from suppliers.models import Supplier
from suppliers.services import create_supplier
from tests.receipts import supplier_receipt

pytestmark = pytest.mark.django_db(transaction=True)


def created_events():
    return AuditEvent.objects.filter(action="supplier.created")


def supplier(actor, code="sup-syn-001", name="Synthetic Ingredients Supply"):
    return create_supplier(
        actor=actor,
        code=code,
        name=name,
        location="Sampletown, Exampleland",
        reason="Synthetic master data",
    )


def received(people, source, number="SYN-SUP-LOT-1", **changes):
    from catalog.tests.factories import approved_rules

    return receive_lot(
        actor=people["analyst"],
        number=number,
        material="Synthetic powder",
        rules=approved_rules(people["author"]),
        reason="Synthetic receipt",
        receipt=supplier_receipt(source, **changes),
    )


def test_quality_creates_a_supplier_with_an_audit_event(people):
    created = supplier(people["author"])
    assert (created.code, created.location) == ("sup-syn-001", "Sampletown, Exampleland")
    event = AuditEvent.objects.get(action="supplier.created")
    assert (event.actor, event.object_type, event.object_id) == (
        people["author"],
        "suppliers.supplier",
        str(created.pk),
    )
    assert event.after["code"] == "sup-syn-001" and event.reason == "Synthetic master data"


@pytest.mark.parametrize("role", ["analyst", "reviewer", "admin", "auditor"])
def test_only_quality_adds_suppliers(people, role):
    with pytest.raises(PermissionDenied):
        supplier(people[role])
    assert not Supplier.objects.exists() and not created_events().exists()


def test_supplier_needs_a_reason_a_name_and_a_new_code(people):
    with pytest.raises(ValidationError, match="reason is required"):
        create_supplier(
            actor=people["author"], code="sup-a", name="Synthetic A", location="X", reason="  "
        )
    with pytest.raises(ValidationError):
        create_supplier(
            actor=people["author"], code="sup-a", name="  ", location="X", reason="Synthetic"
        )
    with pytest.raises(ValidationError):
        create_supplier(
            actor=people["author"], code="Not A Slug", name="A", location="X", reason="Synthetic"
        )
    supplier(people["author"])
    with pytest.raises(ValidationError):
        supplier(people["approver"])
    assert Supplier.objects.count() == 1 and created_events().count() == 1


def test_supplier_identity_cannot_be_changed_or_deleted(people):
    created = supplier(people["author"])
    for action in [
        lambda: Supplier.objects.filter(pk=created.pk).update(name="Changed"),
        lambda: Supplier.objects.filter(pk=created.pk).delete(),
    ]:
        with pytest.raises(DatabaseError), transaction.atomic():
            action()
    created.refresh_from_db()
    assert created.name == "Synthetic Ingredients Supply"


@pytest.mark.parametrize("role", ["analyst", "reviewer", "auditor", "admin", "author"])
def test_list_is_readable_by_laboratory_roles(client, people, role):
    client.force_login(people[role])
    body = client.get(reverse("suppliers:list")).content.decode()
    assert "No suppliers yet" in body
    assert ("New supplier" in body) is (role == "author")
    supplier(people["author"])
    body = client.get(reverse("suppliers:list")).content.decode()
    assert "sup-syn-001" in body and "Sampletown, Exampleland" in body


def test_pages_are_denied_without_a_laboratory_role(client, people):
    created = supplier(people["author"])
    outsider = get_user_model().objects.create_user("outsider", password="x-synthetic-91")
    client.force_login(outsider)
    for url in [
        reverse("suppliers:list"),
        reverse("suppliers:new"),
        reverse("suppliers:detail", args=[created.pk]),
    ]:
        assert client.get(url).status_code == 403


@pytest.mark.parametrize("role", ["analyst", "reviewer", "auditor", "admin"])
def test_new_supplier_page_is_for_quality_only(client, people, role):
    client.force_login(people[role])
    url = reverse("suppliers:new")
    assert client.get(url).status_code == 403
    posted = client.post(
        url, {"code": "sup-x", "name": "Synthetic X", "location": "X", "reason": "Synthetic"}
    )
    assert posted.status_code == 403 and not Supplier.objects.exists()


def test_quality_adds_a_supplier_through_the_form(client, people):
    client.force_login(people["author"])
    url = reverse("suppliers:new")
    assert "does not qualify it" in client.get(url).content.decode()
    data = {
        "code": "sup-syn-002",
        "name": "Example Packaging Works",
        "location": "Testville, Exampleland",
        "reason": "Synthetic master data",
    }
    missing = client.post(url, data | {"reason": ""})
    assert missing.status_code == 422 and not Supplier.objects.exists()
    response = client.post(url, data)
    created = Supplier.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("suppliers:detail", args=[created.pk])
    duplicate = client.post(url, data)
    assert duplicate.status_code == 422
    assert "This supplier code already exists." in duplicate.content.decode()
    assert Supplier.objects.count() == 1


def test_list_search_sort_and_filtered_empty_state(client, people):
    supplier(people["author"], code="sup-b", name="Alpha Synthetic")
    supplier(people["author"], code="sup-a", name="Zeta Synthetic")
    client.force_login(people["analyst"])
    url = reverse("suppliers:list")
    body = client.get(url).content.decode()
    assert body.index("sup-a") < body.index("sup-b")
    body = client.get(url, {"sort": "name"}).content.decode()
    assert body.index("sup-b") < body.index("sup-a")
    body = client.get(url, {"q": "zeta"}).content.decode()
    assert "sup-a" in body and "sup-b" not in body
    body = client.get(url, {"q": "nothing-matches"}).content.decode()
    assert "No suppliers match these filters" in body and "Clear filters" in body


def test_record_lists_lots_whose_current_receipt_names_the_supplier(client, people):
    first = supplier(people["author"])
    second = supplier(people["author"], code="sup-syn-002", name="Example Packaging Works")
    lot = received(people, first)
    client.force_login(people["auditor"])
    first_url = reverse("suppliers:detail", args=[first.pk])
    second_url = reverse("suppliers:detail", args=[second.pk])
    body = client.get(first_url).content.decode()
    assert "SYN-SUP-LOT-1" in body and "SUP-LOT-SYN-001" in body and "25 kg" in body
    assert "supplier.created" in body
    assert "Not recorded in this register" in body
    assert "No lots received from this supplier" in client.get(second_url).content.decode()
    listing = client.get(reverse("suppliers:list")).content.decode()
    assert '<td class="text-end">1</td>' in listing and '<td class="text-end">0</td>' in listing

    # A correction that names another supplier moves the lot; the original record is kept.
    correct_receipt(
        actor=people["analyst"],
        receipt=current_receipt(lot),
        reason="Synthetic supplier named in error",
        **supplier_receipt(second),
    )
    assert "No lots received from this supplier" in client.get(first_url).content.decode()
    assert "SYN-SUP-LOT-1" in client.get(second_url).content.decode()
    assert Lot.objects.get(pk=lot.pk).receipts.count() == 2


def test_concurrent_duplicate_code_is_a_conflict_not_a_fault(client, people, monkeypatch):
    from catalog.tests.factories import commit_first_on_save

    author = people["author"]

    def competitor():
        Supplier.objects.create(
            code="sup-race", name="Other request", location="X", created_by=author
        )

    commit_first_on_save(monkeypatch, Supplier, competitor)
    client.force_login(author)
    response = client.post(
        reverse("suppliers:new"),
        {"code": "sup-race", "name": "Synthetic", "location": "X", "reason": "Synthetic"},
    )
    assert response.status_code == 422
    assert "Another request saved a conflicting record" in response.content.decode()
    assert Supplier.objects.get().name == "Other request"
    assert not created_events().exists()
