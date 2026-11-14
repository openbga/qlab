"""The supplier register: who supplies material. Identity only; qualification is not held here."""

from django.core.exceptions import ValidationError
from django.db import transaction

from core.audit import record_event, snapshot
from core.services import require_role

from .models import Supplier

AUTHOR_ROLE = "quality"
READ_ROLES = ("analyst", "reviewer", "quality", "admin", "auditor")


@transaction.atomic
def create_supplier(*, actor, code, name, location, reason):
    require_role(actor, AUTHOR_ROLE)
    if not (reason or "").strip():
        raise ValidationError("A reason is required.")
    supplier = Supplier(
        code=code, name=(name or "").strip(), location=(location or "").strip(), created_by=actor
    )
    supplier.full_clean()
    supplier.save()
    record_event(
        actor=actor,
        action="supplier.created",
        obj=supplier,
        after=snapshot(supplier),
        reason=reason,
    )
    return supplier
