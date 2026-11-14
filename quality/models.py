from django.conf import settings
from django.db import models
from django.db.models import Q

from catalog.units import QUANTITY_UNITS, plain


class Lot(models.Model):
    number = models.CharField(max_length=80, unique=True)
    material = models.CharField(max_length=160)
    rules = models.ForeignKey("core.RuleSet", on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    state = models.CharField(max_length=24, default="quarantine")
    disposition_evidence = models.JSONField(default=dict, blank=True)
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number


class ReceiptSource(models.TextChoices):
    SUPPLIER = "supplier", "Received from a supplier"
    ON_SITE = "on_site", "Made on site"


class ReceiptCondition(models.TextChoices):
    ACCEPTABLE = "acceptable", "No discrepancy found"
    DISCREPANCY = "discrepancy", "Discrepancy found"


class LotReceipt(models.Model):
    """Where a lot came from and what arrived. Append-only; a correction adds a linked record.

    A lot has one original record and a single chain of corrections; the record that nothing
    corrects is the current one.
    """

    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="receipts")
    source = models.CharField(max_length=12, choices=ReceiptSource.choices)
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receipts",
    )
    supplier_lot = models.CharField("Supplier lot number", max_length=80, blank=True)
    manufacturer = models.CharField(max_length=160, blank=True)
    manufacturer_location = models.CharField(max_length=160, blank=True)
    manufacturer_lot = models.CharField("Manufacturer lot number", max_length=80, blank=True)
    shipment_ref = models.CharField("Delivery or batch document", max_length=120)
    received_on = models.DateField("Date received")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    quantity_unit = models.CharField(max_length=8, choices=QUANTITY_UNITS)
    containers = models.PositiveIntegerField("Number of containers")
    container_description = models.CharField("Containers", max_length=160)
    condition = models.CharField(
        "Examination on receipt", max_length=12, choices=ReceiptCondition.choices
    )
    condition_notes = models.TextField("Examination notes", blank=True)
    reason = models.TextField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    corrects = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="corrected_by"
    )

    class Meta:
        ordering = ["recorded_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["lot"], condition=Q(corrects__isnull=True), name="lot_receipt_one_original"
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="lot_receipt_quantity"),
            models.CheckConstraint(condition=Q(containers__gte=1), name="lot_receipt_containers"),
            models.CheckConstraint(
                condition=(Q(source="supplier") & Q(supplier__isnull=False))
                | (
                    Q(source="on_site")
                    & Q(supplier__isnull=True)
                    & Q(supplier_lot="")
                    & Q(manufacturer="")
                    & Q(manufacturer_location="")
                    & Q(manufacturer_lot="")
                ),
                name="lot_receipt_source_shape",
            ),
            models.CheckConstraint(
                condition=~Q(manufacturer="")
                | (Q(manufacturer_location="") & Q(manufacturer_lot="")),
                name="lot_receipt_manufacturer_named",
            ),
            models.CheckConstraint(
                condition=Q(condition="acceptable")
                | (Q(condition="discrepancy") & ~Q(condition_notes="")),
                name="lot_receipt_examination",
            ),
            models.CheckConstraint(
                condition=~Q(shipment_ref="") & ~Q(container_description="") & ~Q(reason=""),
                name="lot_receipt_stated",
            ),
        ]

    def __str__(self):
        return f"Receipt of {self.lot}"

    @property
    def quantity_text(self):
        return plain(self.quantity)

    @property
    def has_discrepancy(self):
        return self.condition == ReceiptCondition.DISCREPANCY


class Sample(models.Model):
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="samples")
    reference = models.CharField(max_length=80, unique=True)
    collected_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def __str__(self):
        return self.reference


class Result(models.Model):
    sample = models.ForeignKey(Sample, on_delete=models.PROTECT, related_name="results")
    test_code = models.CharField(max_length=80)
    value = models.DecimalField(max_digits=20, decimal_places=8)
    unit = models.CharField(max_length=40)
    lower_limit = models.DecimalField(max_digits=20, decimal_places=8)
    upper_limit = models.DecimalField(max_digits=20, decimal_places=8)
    analyst = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)
    state = models.CharField(max_length=24, default="recorded")
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sample", "test_code"], name="sample_test_unique"),
            models.CheckConstraint(
                condition=models.Q(lower_limit__lte=models.F("upper_limit")),
                name="result_limits_ordered",
            ),
        ]

    @property
    def conforms(self):
        return self.lower_limit <= self.value <= self.upper_limit
