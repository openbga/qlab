from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from catalog.web import can, form_status, history, page, run, sorted_by
from core.services import require_role

from . import services
from .forms import SupplierForm
from .models import Supplier

SECTION = "Suppliers"
# A lot's receipt details are append-only; the record without a correction is the current one.
CURRENT = Q(receipts__corrected_by__isnull=True)


def read_access(request):
    require_role(request.user, *services.READ_ROLES)


@login_required
def supplier_list(request):
    read_access(request)
    suppliers = Supplier.objects.annotate(lot_count=Count("receipts", filter=CURRENT))
    query = request.GET.get("q", "").strip()
    if query:
        suppliers = suppliers.filter(
            Q(code__icontains=query) | Q(name__icontains=query) | Q(location__icontains=query)
        )
    suppliers, sort = sorted_by(
        request,
        suppliers,
        {
            "code": ["code"],
            "-code": ["-code"],
            "name": ["name", "code"],
            "-name": ["-name", "code"],
        },
        "code",
    )
    return render(
        request,
        "suppliers/list.html",
        {
            "page_title": SECTION,
            "page_obj": page(request, suppliers),
            "query": query,
            "sort": sort,
            "filtered": bool(query),
            "can_edit": can(request.user, services.AUTHOR_ROLE),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def supplier_new(request):
    require_role(request.user, services.AUTHOR_ROLE)
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = run(
            form, lambda: services.create_supplier(actor=request.user, **form.cleaned_data)
        )
        if supplier:
            messages.success(request, f"Supplier {supplier.code} created.")
            return redirect("suppliers:detail", pk=supplier.pk)
    return render(
        request,
        "catalog/form.html",
        {
            "page_title": "New supplier",
            "form": form,
            "crumbs": [(SECTION, reverse("suppliers:list")), ("New supplier", None)],
            "cancel_url": reverse("suppliers:list"),
            "submit_label": "Create supplier",
            "intro": "A supplier's identity cannot be edited after creation; use synthetic names "
            "only. Adding a supplier does not qualify it.",
        },
        status=form_status(request, form),
    )


@login_required
def supplier_detail(request, pk):
    read_access(request)
    supplier = get_object_or_404(Supplier.objects.select_related("created_by"), pk=pk)
    receipts = (
        supplier.receipts.filter(corrected_by__isnull=True)
        .select_related("lot")
        .order_by("-received_on", "-id")
    )
    return render(
        request,
        "suppliers/detail.html",
        {
            "page_title": supplier.code,
            "supplier": supplier,
            "crumbs": [(SECTION, reverse("suppliers:list")), (supplier.code, None)],
            "page_obj": page(request, receipts),
            "history": history(supplier),
        },
    )
