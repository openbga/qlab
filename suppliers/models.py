from django.conf import settings
from django.db import models


class Supplier(models.Model):
    """Identity of a company that supplies material. Immutable once created.

    The register says who a supplier is, not whether it is qualified: a lot's receipt names
    its supplier, and reliance on a supplier's results is a separate, later decision.
    """

    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=160)
    location = models.CharField(
        max_length=160, help_text="Site the material is supplied from: town and country."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.name}"
