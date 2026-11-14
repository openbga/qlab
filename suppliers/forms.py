from django import forms

from catalog.forms import GroupedForm, reason_field

from .models import Supplier


class SupplierForm(GroupedForm):
    code = forms.SlugField(max_length=60, help_text="Short stable identifier, e.g. sup-syn-001.")
    name = forms.CharField(max_length=160)
    location = forms.CharField(
        max_length=160, help_text="Site the material is supplied from: town and country."
    )
    reason = reason_field("Reason")
    groups = [("Supplier", ["code", "name", "location"]), ("Change control", ["reason"])]

    def clean_code(self):
        code = self.cleaned_data["code"]
        if Supplier.objects.filter(code=code).exists():
            raise forms.ValidationError("This supplier code already exists.")
        return code
