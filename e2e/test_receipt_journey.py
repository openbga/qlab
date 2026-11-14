"""Supplier register and lot receipt details through the pages, in Chromium."""

import re

import pytest
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from core.models import AuditEvent
from quality.models import Lot
from quality.services import current_receipt
from suppliers.models import Supplier
from tests.test_lot_receipt import PASSWORD, approved_rules, staff


@pytest.mark.django_db(transaction=True)
def test_supplier_then_receipt_then_correction(live_server, django_user_model, artifacts):
    people = staff(django_user_model)
    approved_rules(people)
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))

        def login(username):
            page.goto(live_server.url + reverse("login"))
            page.get_by_label(re.compile(r"^Username\b")).fill(username)
            page.get_by_label(re.compile(r"^Password\b")).fill(PASSWORD)
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page).to_have_url(live_server.url + "/")

        def sign_out():
            page.get_by_role("button", name="Sign out", exact=True).click()

        def field(label):
            return page.get_by_label(re.compile(r"^" + re.escape(label) + r"\b"))

        def no_sideways_scroll():
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        nav = page.get_by_role("navigation", name="Primary", exact=True)

        # Quality adds the supplier; the register does not qualify it.
        login("quality")
        nav.get_by_role("link", name="Suppliers", exact=True).click()
        expect(page.get_by_role("heading", name="Suppliers", exact=True, level=1)).to_be_visible()
        expect(page.locator('#vr-nav [aria-current="page"]')).to_have_text("Suppliers")
        expect(page.get_by_text("No suppliers yet")).to_be_visible()
        page.locator(".vr-page-actions").get_by_role("link", name="New supplier").click()
        field("Code").fill("sup-syn-001")
        field("Name").fill("Synthetic Ingredients Supply")
        field("Location").fill("Sampletown, Exampleland")
        field("Reason").fill("Synthetic supplier added to the register")
        page.get_by_role("button", name="Create supplier", exact=True).click()
        expect(page.get_by_text("Supplier sup-syn-001 created.")).to_be_visible()
        expect(page.get_by_text("No lots received from this supplier")).to_be_visible()
        expect(page.get_by_text("Not recorded in this register")).to_be_visible()
        sign_out()

        # The analyst receives a lot; incomplete receipt details are refused and kept on screen.
        login("analyst")
        page.locator(".vr-page-actions").get_by_role("link", name="New material lot").click()
        expect(page.locator('#vr-nav [aria-current="page"]')).to_have_text("Lots")
        field("Lot number").fill("SYN-BROWSER-R-001")
        field("Material").fill("Synthetic botanical extract")
        field("Rule set").select_option(label="synthetic v1")
        field("Source").select_option(label="Received from a supplier")
        field("Supplier lot number").fill("SUP-LOT-SYN-001")
        field("Delivery or batch document").fill("DN-SYN-0042")
        field("Quantity received").fill("125.50")
        field("Quantity unit").select_option(label="kg")
        field("Number of containers").fill("5")
        field("Containers").fill("25 kg fibre drums")
        field("Examination on receipt").select_option(label="Discrepancy found")
        field("Reason").fill("Synthetic delivery received")
        page.get_by_role("button", name="Receive lot", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("Your entries were kept.")
        expect(page.get_by_text("Select the supplier the lot was received from.")).to_be_visible()
        expect(page.get_by_text("Describe the discrepancy found on receipt.")).to_be_visible()
        expect(field("Lot number")).to_have_value("SYN-BROWSER-R-001")
        page.get_by_label("Supplier", exact=True).select_option(
            label="sup-syn-001 · Synthetic Ingredients Supply"
        )
        field("Examination notes").fill("Synthetic drum 3 arrived with a torn outer label.")
        page.screenshot(path=str(artifacts / "receipt-new-lot-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        no_sideways_scroll()
        page.screenshot(path=str(artifacts / "receipt-new-lot-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="Receive lot", exact=True).click()

        expect(page.get_by_text("Lot received in quarantine.")).to_be_visible()
        lot_url = page.url
        receipt = page.locator("section", has=page.get_by_role("heading", name="Receipt"))
        expect(receipt).to_contain_text("Received from a supplier")
        expect(receipt).to_contain_text("SUP-LOT-SYN-001")
        expect(receipt).to_contain_text("125.5 kg")
        expect(receipt).to_contain_text("5 · 25 kg fibre drums")
        expect(receipt).to_contain_text("Discrepancy found")
        expect(receipt).to_contain_text("A discrepancy does not hold the lot by itself.")
        expect(receipt.get_by_role("link", name="sup-syn-001")).to_be_visible()

        # A correction opens with the current details and adds a linked record.
        receipt.get_by_role("link", name="Correct receipt details").click()
        expect(
            page.get_by_role("heading", name="Correct receipt details", exact=True)
        ).to_be_visible()
        expect(field("Supplier lot number")).to_have_value("SUP-LOT-SYN-001")
        expect(field("Quantity received")).to_have_value("125.5")
        page.get_by_role("button", name="Correct receipt details", exact=True).click()
        expect(page.get_by_role("alert")).to_be_visible()  # A reason is required.
        field("Reason for correction").fill("Nothing changed")
        page.get_by_role("button", name="Correct receipt details", exact=True).click()
        expect(page.get_by_text("The correction changes nothing.")).to_be_visible()
        field("Supplier lot number").fill("SUP-LOT-SYN-002")
        field("Reason for correction").fill("Supplier lot misread from the drum label")
        toggle = page.get_by_role("button", name="Page documentation", exact=True)
        panel = page.get_by_role("complementary", name="Page documentation", exact=True)
        toggle.click()
        expect(panel.locator("[data-pagedocs-for]")).to_have_attribute(
            "data-pagedocs-for", "quality:receipt_correct"
        )
        expect(panel.get_by_role("heading", name="Rules and hidden logic")).to_be_visible()
        toggle.click()
        page.get_by_role("button", name="Correct receipt details", exact=True).click()

        expect(page).to_have_url(lot_url)
        expect(page.get_by_text("Receipt details corrected; the original is kept.")).to_be_visible()
        receipt = page.locator("section", has=page.get_by_role("heading", name="Receipt"))
        expect(receipt.locator(".vr-history-item")).to_have_count(2)
        corrected = receipt.locator(".vr-history-item").nth(1)
        expect(corrected).to_contain_text("Receipt details corrected")
        expect(corrected.locator("del")).to_have_text("SUP-LOT-SYN-001")
        expect(corrected).to_contain_text("SUP-LOT-SYN-002")
        expect(corrected).to_contain_text("Supplier lot misread from the drum label")
        page.screenshot(path=str(artifacts / "receipt-lot-record-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        no_sideways_scroll()
        page.screenshot(path=str(artifacts / "receipt-lot-record-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        sign_out()

        # An auditor traces the lot from the supplier and from the supplier's lot number, and
        # cannot change either.
        login("auditor")
        page.get_by_label("Find lot").fill("sup-lot-syn-002")
        page.get_by_role("button", name="Search", exact=True).click()
        row = page.get_by_role("row", name=re.compile("SYN-BROWSER-R-001"))
        expect(row).to_contain_text("Synthetic Ingredients Supply")
        expect(row).to_contain_text("SUP-LOT-SYN-002")
        page.get_by_label("Find lot").fill("sup-lot-syn-001")  # The replaced record is not found.
        page.get_by_role("button", name="Search", exact=True).click()
        expect(page.get_by_text("No material lots match these filters")).to_be_visible()
        nav.get_by_role("link", name="Suppliers", exact=True).click()
        expect(page.get_by_role("link", name="New supplier")).to_have_count(0)
        page.get_by_role("link", name="sup-syn-001", exact=True).click()
        lots = page.locator("section", has=page.get_by_role("heading", name="Lots received"))
        expect(lots.get_by_role("link", name="SYN-BROWSER-R-001")).to_be_visible()
        expect(lots).to_contain_text("SUP-LOT-SYN-002")
        page.set_viewport_size({"width": 390, "height": 844})
        no_sideways_scroll()
        page.screenshot(path=str(artifacts / "receipt-supplier-record-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        lots.get_by_role("link", name="SYN-BROWSER-R-001").click()
        expect(page).to_have_url(lot_url)
        expect(page.get_by_role("link", name="Correct receipt details")).to_have_count(0)
        response = page.goto(lot_url + "receipt/correct/")
        assert response.status == 403
        browser.close()

    assert not errors, errors
    lot = Lot.objects.get(number="SYN-BROWSER-R-001")
    receipt = current_receipt(lot)
    assert (lot.revision, lot.receipts.count()) == (2, 2)
    assert (receipt.supplier, receipt.supplier_lot) == (Supplier.objects.get(), "SUP-LOT-SYN-002")
    assert receipt.corrects.supplier_lot == "SUP-LOT-SYN-001"
    assert list(
        AuditEvent.objects.filter(action__startswith="lot.")
        .order_by("occurred_at")
        .values_list("action", "actor__username")
    ) == [
        ("lot.received", "analyst"),
        ("lot.receipt_recorded", "analyst"),
        ("lot.receipt_corrected", "analyst"),
    ]
