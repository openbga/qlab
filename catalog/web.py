"""View helpers shared by the catalog and sampling pages."""

from functools import reduce
from operator import or_

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import redirect, render
from psycopg.errors import UniqueViolation

from core.models import AuditEvent, ElectronicSignature
from core.services import require_role

from . import services
from .forms import ApprovalForm, ReasonForm
from .models import RevisionStatus

READ_ROLES = services.READ_ROLES
CONFLICT = "Another request saved a conflicting record at the same time. Reload and try again."

# (table, unique constraint) pairs that a concurrent request can legitimately take between this
# request's own uniqueness check and its insert: codes, applicability keys, lot numbers and
# sample references, which are created without a parent row lock. Versions, specification tests
# and QC checks are added under a row lock after their check, so a violation there is a fault,
# as is one on any other table (audit events, signatures, primary keys). Only these become the
# conflict message.
CONCURRENT_DUPLICATES = frozenset(
    {
        ("catalog_material", "catalog_material_code_key"),
        ("catalog_method", "catalog_method_code_key"),
        ("catalog_specification", "catalog_specification_code_key"),
        ("catalog_specification", "specification_applicability_unique"),
        ("sampling_samplingplan", "sampling_samplingplan_code_key"),
        ("sampling_samplingplan", "sampling_plan_unique"),
        ("quality_sample", "quality_sample_reference_key"),
        ("quality_lot", "quality_lot_number_key"),
        ("suppliers_supplier", "suppliers_supplier_code_key"),
    }
)


def can(user, *roles):
    return user.is_authenticated and user.is_active and user.groups.filter(name__in=roles).exists()


def read_access(request):
    require_role(request.user, *READ_ROLES)


def run(form, action):
    """Call a domain action; turn domain refusals into form errors without hiding them."""
    try:
        return action()
    except ValidationError as exc:
        if hasattr(exc, "error_dict"):
            for field, errors in exc.message_dict.items():
                form.add_error(field if field in form.fields else None, errors)
        else:
            form.add_error(None, exc.messages)
    except PermissionDenied as exc:
        form.add_error(None, str(exc) or "Your role does not permit this action.")
    except IntegrityError as exc:
        # The service transaction rolled back. Only a concurrent duplicate is expected (e.g. a
        # double submission committed the same code after this request checked it); every other
        # integrity failure, including any other unique violation, is a fault and is re-raised.
        if not concurrent_duplicate(exc):
            raise
        form.add_error(None, CONFLICT)
    return None


def concurrent_duplicate(exc):
    cause = exc.__cause__
    if not isinstance(cause, UniqueViolation):
        return False
    return (cause.diag.table_name, cause.diag.constraint_name) in CONCURRENT_DUPLICATES


def form_status(request, form):
    return 422 if request.method == "POST" and form.errors else 200


def page(request, queryset, per_page=25):
    try:
        per_page = int(request.GET.get("per_page", per_page))
    except ValueError:
        per_page = 25
    per_page = per_page if per_page in (25, 50, 100) else 25
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def sorted_by(request, queryset, allowed, default):
    key = request.GET.get("sort", default)
    if key not in allowed:
        key = default
    return queryset.order_by(*allowed[key]), key


def history(*objects):
    pairs = [Q(object_type=o._meta.label_lower, object_id=str(o.pk)) for o in objects if o]
    if not pairs:
        return AuditEvent.objects.none()
    return (
        AuditEvent.objects.filter(reduce(or_, pairs))
        .select_related("actor")
        .order_by("occurred_at", "id")
    )


def signatures(*objects):
    pairs = [Q(object_type=o._meta.label_lower, object_id=str(o.pk)) for o in objects if o]
    if not pairs:
        return ElectronicSignature.objects.none()
    return ElectronicSignature.objects.filter(reduce(or_, pairs)).order_by("signed_at")


def status_tone(status):
    return {"draft": "progress", "approved": "success", "withdrawn": "neutral"}.get(status, "info")


def approve_page(request, revision, *, kind, crumbs, success_url, detail_template):
    """Full-page signing action for any controlled revision. The service re-checks everything."""
    require_role(request.user, services.AUTHOR_ROLE)
    form = ApprovalForm(request.POST or None, initial={"expected_revision": revision.revision})
    blocked = ""
    if revision.status != RevisionStatus.DRAFT:
        blocked = "Only draft revisions can be approved."
    else:
        try:
            services.ensure_independent(request.user, revision)
        except PermissionDenied as exc:
            blocked = str(exc)
    if request.method == "POST" and not blocked and form.is_valid():
        approved = run(
            form,
            lambda: services.approve_revision(
                actor=request.user, revision=revision, **form.signing_data()
            ),
        )
        if approved:
            messages.success(request, f"{kind} {approved} approved and signed.")
            return redirect(success_url)
    status = 403 if blocked else form_status(request, form)
    return render(
        request,
        "catalog/approve.html",
        {
            "page_title": f"Approve {kind.lower()} {revision}",
            "kind": kind,
            "revision": revision,
            "form": form,
            "blocked": blocked,
            "crumbs": crumbs,
            "cancel_url": success_url,
            "detail_template": detail_template,
        },
        status=status,
    )


def withdraw_page(request, revision, *, kind, crumbs, success_url):
    require_role(request.user, services.AUTHOR_ROLE)
    if revision.status != RevisionStatus.DRAFT:
        messages.error(request, "Only draft revisions can be withdrawn.")
        return redirect(success_url)
    form = ReasonForm(request.POST or None, initial={"expected_revision": revision.revision})
    if request.method == "POST" and form.is_valid():
        done = run(
            form,
            lambda: services.withdraw_revision(
                actor=request.user,
                revision=revision,
                expected_revision=form.cleaned_data["expected_revision"],
                reason=form.cleaned_data["reason"],
            ),
        )
        if done:
            messages.success(request, f"Draft {revision} withdrawn.")
            return redirect(success_url)
    return render(
        request,
        "catalog/form.html",
        {
            "page_title": f"Withdraw draft {revision}",
            "form": form,
            "crumbs": crumbs,
            "cancel_url": success_url,
            "submit_label": "Withdraw draft",
            "submit_tone": "danger",
            "intro": "A withdrawn draft stays in the history and can no longer be edited or "
            "approved. Create a new version to continue.",
        },
        status=form_status(request, form),
    )
