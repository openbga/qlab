from django import forms
from django.utils import timezone

from catalog.forms import GroupedForm, reason_field
from catalog.units import QUANTITY_UNITS
from core.models import RuleSet
from suppliers.models import Supplier

from .models import Lot, ReceiptCondition, ReceiptSource, Sample
from .services import RECEIPT_FIELDS


class StyledForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), max_length=2000)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


RECEIPT_GROUPS = [
    (
        "Source",
        [
            "source",
            "supplier",
            "supplier_lot",
            "manufacturer",
            "manufacturer_location",
            "manufacturer_lot",
        ],
    ),
    (
        "Delivery",
        [
            "shipment_ref",
            "received_on",
            "quantity",
            "quantity_unit",
            "containers",
            "container_description",
        ],
    ),
    ("Examination on receipt", ["condition", "condition_notes"]),
]


# Menus open on no choice: a source, a unit and an examination outcome are stated, not assumed.
UNSTATED = [("", "—")]


class ReceiptForm(GroupedForm):
    """Receipt details of one lot. The service repeats every rule under the lot lock."""

    source = forms.ChoiceField(choices=UNSTATED + ReceiptSource.choices)
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.all(),
        required=False,
        help_text="Required for a lot received from a supplier. A quality user adds suppliers "
        "to the register.",
    )
    supplier_lot = forms.CharField(
        label="Supplier lot number",
        max_length=80,
        required=False,
        help_text="As printed on the supplier's label or documents. Leave blank if not known.",
    )
    manufacturer = forms.CharField(
        max_length=160,
        required=False,
        help_text="The manufacturer, when it is not the supplier and is known.",
    )
    manufacturer_location = forms.CharField(max_length=160, required=False)
    manufacturer_lot = forms.CharField(
        label="Manufacturer lot number", max_length=80, required=False
    )
    shipment_ref = forms.CharField(
        label="Delivery or batch document",
        max_length=120,
        help_text="Delivery note, packing list or purchase order. For material made on site, "
        "the batch record or production order.",
    )
    received_on = forms.DateField(
        label="Date received",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        initial=timezone.localdate,
    )
    quantity = forms.DecimalField(label="Quantity received", max_digits=14, decimal_places=4)
    quantity_unit = forms.ChoiceField(label="Quantity unit", choices=UNSTATED + QUANTITY_UNITS)
    containers = forms.IntegerField(label="Number of containers", min_value=1)
    container_description = forms.CharField(
        label="Containers", max_length=160, help_text="Type and size, e.g. 25 kg fibre drums."
    )
    condition = forms.ChoiceField(
        label="Examination on receipt",
        choices=UNSTATED + ReceiptCondition.choices,
        help_text="Labels, seals, container condition and delivery documents, as your "
        "receiving procedure requires.",
    )
    condition_notes = forms.CharField(
        label="Examination notes",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Required when a discrepancy was found: what was wrong and with which "
        "containers.",
    )
    reason = reason_field("Reason")
    groups = [*RECEIPT_GROUPS, ("Change control", ["reason"])]

    def receipt_values(self):
        return {name: self.cleaned_data[name] for name in RECEIPT_FIELDS}


class ReceiptCorrectionForm(ReceiptForm):
    """A correction names the record it replaces, so a page opened before another correction
    is refused instead of replacing details the user never saw."""

    receipt = forms.IntegerField(widget=forms.HiddenInput)
    reason = reason_field("Reason for correction")


class LotForm(ReceiptForm):
    number = forms.CharField(label="Lot number", max_length=80)
    material = forms.CharField(max_length=160)
    rules = forms.ModelChoiceField(label="Rule set", queryset=RuleSet.objects.none())
    groups = [
        ("Lot", ["number", "material", "rules"]),
        *RECEIPT_GROUPS,
        ("Change control", ["reason"]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rules"].queryset = RuleSet.objects.filter(status="approved")

    def clean_number(self):
        number = self.cleaned_data["number"]
        if Lot.objects.filter(number=number).exists():
            raise forms.ValidationError("This lot number already exists.")
        return number


class SampleForm(StyledForm):
    reference = forms.CharField(max_length=80)
    collected_at = forms.DateTimeField(initial=timezone.now)

    def clean_reference(self):
        reference = self.cleaned_data["reference"]
        if Sample.objects.filter(reference=reference).exists():
            raise forms.ValidationError("This sample reference already exists.")
        return reference


class ResultForm(StyledForm):
    test_code = forms.CharField(max_length=80, initial="identity")
    value = forms.DecimalField(max_digits=20, decimal_places=8)
    unit = forms.CharField(max_length=40)
    lower_limit = forms.DecimalField(max_digits=20, decimal_places=8)
    upper_limit = forms.DecimalField(max_digits=20, decimal_places=8)

    def clean(self):
        values = super().clean()
        if (
            values.get("lower_limit") is not None
            and values.get("upper_limit") is not None
            and values["lower_limit"] > values["upper_limit"]
        ):
            raise forms.ValidationError("The lower limit must not exceed the upper limit.")
        return values


class SigningForm(StyledForm):
    signature_username = forms.CharField(label="Signing username", max_length=150)
    pin = forms.CharField(
        label="Signature PIN",
        widget=forms.PasswordInput(attrs={"autocomplete": "off", "inputmode": "numeric"}),
    )
    expected_revision = forms.IntegerField(widget=forms.HiddenInput)
