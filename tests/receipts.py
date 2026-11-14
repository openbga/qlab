"""Synthetic receipt details for tests that receive a lot through quality.services."""

from decimal import Decimal

from django.utils import timezone


def on_site_receipt(**changes):
    """Receipt details of a lot made on site; pass keyword arguments to vary a field."""
    return {
        "source": "on_site",
        "supplier": None,
        "supplier_lot": "",
        "manufacturer": "",
        "manufacturer_location": "",
        "manufacturer_lot": "",
        "shipment_ref": "BR-SYN-001",
        "received_on": timezone.localdate(),
        "quantity": Decimal("25"),
        "quantity_unit": "kg",
        "containers": 1,
        "container_description": "Synthetic 25 kg drum",
        "condition": "acceptable",
        "condition_notes": "",
    } | changes


def supplier_receipt(supplier, **changes):
    """Receipt details of a lot received from a supplier on the register."""
    return (
        on_site_receipt(
            source="supplier",
            supplier=supplier,
            supplier_lot="SUP-LOT-SYN-001",
            shipment_ref="DN-SYN-001",
        )
        | changes
    )
