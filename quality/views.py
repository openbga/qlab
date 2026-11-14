from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from accounts.services import ROLES
from catalog.web import form_status, run
from core.models import ElectronicSignature
from core.services import require_role

from . import services
from .forms import LotForm, ReceiptCorrectionForm, ReceiptForm, ResultForm, SampleForm, SigningForm
from .models import Lot, LotReceipt, Result, Sample

LOTS = "Material lots"
# Labels of the receipt details, in the order the lot record and its history show them.
RECEIPT_LABELS = (
    ("source", "Source"),
    ("supplier", "Supplier"),
    ("supplier_lot", "Supplier lot number"),
    ("manufacturer", "Manufacturer"),
    ("manufacturer_location", "Manufacturer location"),
    ("manufacturer_lot", "Manufacturer lot number"),
    ("shipment_ref", "Delivery or batch document"),
    ("received_on", "Date received"),
    ("quantity", "Quantity received"),
    ("containers", "Number of containers"),
    ("container_description", "Containers"),
    ("condition", "Examination on receipt"),
    ("condition_notes", "Examination notes"),
)


def access(user):
    require_role(user, "analyst", "reviewer", "quality", "admin", "auditor")


@login_required
def lot_list(request):
    if (
        request.method in {"GET", "HEAD"}
        and not request.user.groups.filter(name__in=ROLES).exists()
    ):
        return redirect("accounts:access")
    access(request.user)
    current = LotReceipt.objects.filter(corrected_by__isnull=True)
    lots = Lot.objects.select_related("rules").prefetch_related(
        Prefetch("receipts", queryset=current.select_related("supplier"), to_attr="current")
    )
    query = request.GET.get("q", "").strip()
    if query:
        lots = lots.filter(
            Q(number__icontains=query)
            | Exists(
                current.filter(lot=OuterRef("pk")).filter(
                    Q(supplier_lot__icontains=query) | Q(manufacturer_lot__icontains=query)
                )
            )
        )
    return render(
        request,
        "quality/lot_list.html",
        {
            "page_title": "Material lots",
            "page_obj": Paginator(lots, 30).get_page(request.GET.get("page")),
            "query": query,
            "can_receive": request.user.groups.filter(name="analyst").exists(),
        },
    )


@login_required
def lot_detail(request, pk):
    access(request.user)
    lot = get_object_or_404(Lot.objects.select_related("rules"), pk=pk)
    from sampling.services import current_assignment

    assignment = current_assignment(lot)
    receipts = list(lot.receipts.select_related("supplier", "recorded_by"))
    corrected = {receipt.corrects_id for receipt in receipts}
    return render(
        request,
        "quality/lot_detail.html",
        {
            "lot": lot,
            "receipt": next((r for r in receipts if r.pk not in corrected), None),
            "receipt_history": receipt_history(receipts),
            "can_record": request.user.groups.filter(name="analyst").exists(),
            "can_review": request.user.groups.filter(name="reviewer").exists(),
            "can_dispose": request.user.groups.filter(name="quality").exists(),
            "can_issue_coa": request.user.groups.filter(name="quality").exists(),
            "reports": lot.reports.all(),
            "assignment": assignment,
            "samples": lot.samples.prefetch_related("results__analyst"),
            "signatures": ElectronicSignature.objects.filter(
                object_type="quality.lot", object_id=str(lot.pk)
            ).order_by("signed_at"),
            "result_signatures": ElectronicSignature.objects.filter(
                object_type="quality.result",
                object_id__in=[
                    str(pk)
                    for pk in Result.objects.filter(sample__lot=lot).values_list("pk", flat=True)
                ],
            ).order_by("signed_at"),
        },
    )


def receipt_display(receipt):
    """Receipt details as the words the lot record shows, keyed like RECEIPT_LABELS."""
    return {
        "source": receipt.get_source_display(),
        "supplier": str(receipt.supplier) if receipt.supplier_id else "",
        "supplier_lot": receipt.supplier_lot,
        "manufacturer": receipt.manufacturer,
        "manufacturer_location": receipt.manufacturer_location,
        "manufacturer_lot": receipt.manufacturer_lot,
        "shipment_ref": receipt.shipment_ref,
        "received_on": receipt.received_on.isoformat(),
        "quantity": f"{receipt.quantity_text} {receipt.quantity_unit}",
        "containers": str(receipt.containers),
        "container_description": receipt.container_description,
        "condition": receipt.get_condition_display(),
        "condition_notes": receipt.condition_notes,
    }


def receipt_history(receipts):
    """Every receipt record of a lot, oldest first; a correction lists what it changed."""
    shown = {receipt.pk: receipt_display(receipt) for receipt in receipts}
    return [
        {
            "receipt": receipt,
            "title": "Receipt details corrected" if receipt.corrects_id else "Receipt recorded",
            "changes": [
                (label, shown[receipt.corrects_id][key], shown[receipt.pk][key])
                for key, label in RECEIPT_LABELS
                if shown[receipt.corrects_id][key] != shown[receipt.pk][key]
            ]
            if receipt.corrects_id
            else [],
        }
        for receipt in receipts
    ]


def form_page(request, form, title, submit):
    return render(
        request,
        "quality/form.html",
        {"form": form, "title": title, "submit": submit},
        status=422 if request.method == "POST" else 200,
    )


def perform(form, action):
    try:
        return action()
    except ValidationError as exc:
        form.add_error(None, "; ".join(exc.messages))
        return None


def receipt_page(request, form, *, title, crumbs, cancel_url, submit, intro, facts=None):
    return render(
        request,
        "catalog/form.html",
        {
            "page_title": title,
            "form": form,
            "crumbs": crumbs,
            "cancel_url": cancel_url,
            "submit_label": submit,
            "intro": intro,
            "facts": facts or [],
        },
        status=form_status(request, form),
    )


def lot_crumbs(lot, action):
    return [
        (LOTS, reverse("quality:lot_list")),
        (lot.number, reverse("quality:lot_detail", args=[lot.pk])),
        (action, None),
    ]


def lot_facts(lot):
    return [("Lot", lot.number), ("Material", lot.material), ("Status", lot.state.capitalize())]


@login_required
@require_http_methods(["GET", "POST"])
def lot_new(request):
    require_role(request.user, "analyst")
    form = LotForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        lot = run(
            form,
            lambda: services.receive_lot(
                actor=request.user,
                number=data["number"],
                material=data["material"],
                rules=data["rules"],
                reason=data["reason"],
                receipt=form.receipt_values(),
            ),
        )
        if lot:
            messages.success(request, "Lot received in quarantine.")
            return redirect("quality:lot_detail", pk=lot.pk)
    return receipt_page(
        request,
        form,
        title="New material lot",
        crumbs=[(LOTS, reverse("quality:lot_list")), ("New material lot", None)],
        cancel_url=reverse("quality:lot_list"),
        submit="Receive lot",
        intro="Receive a lot into quarantine with the details of its receipt: where it came "
        "from, what arrived and what the examination on receipt found.",
    )


@login_required
@require_http_methods(["GET", "POST"])
def receipt_new(request, pk):
    """Receipt details for a lot that has none: one received before they were kept."""
    require_role(request.user, "analyst")
    lot = get_object_or_404(Lot, pk=pk)
    lot_url = reverse("quality:lot_detail", args=[lot.pk])
    if lot.state != "quarantine" or lot.receipts.exists():
        messages.error(
            request,
            "Only quarantined lots accept receipt details."
            if lot.state != "quarantine"
            else "Receipt details are already recorded; correct them instead.",
        )
        return redirect(lot_url)
    form = ReceiptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        receipt = run(
            form,
            lambda: services.record_receipt(
                actor=request.user,
                lot=lot,
                reason=form.cleaned_data["reason"],
                **form.receipt_values(),
            ),
        )
        if receipt:
            messages.success(request, "Receipt details recorded.")
            return redirect(lot_url)
    return receipt_page(
        request,
        form,
        title="Record receipt details",
        crumbs=lot_crumbs(lot, "Record receipt details"),
        cancel_url=lot_url,
        submit="Record receipt details",
        intro="This lot was received before receipt details were kept. Record them from the "
        "delivery documents.",
        facts=lot_facts(lot),
    )


@login_required
@require_http_methods(["GET", "POST"])
def receipt_correct(request, pk):
    require_role(request.user, "analyst")
    lot = get_object_or_404(Lot, pk=pk)
    lot_url = reverse("quality:lot_detail", args=[lot.pk])
    current = services.current_receipt(lot)
    if lot.state != "quarantine" or current is None:
        messages.error(
            request,
            "Only quarantined lots accept receipt corrections."
            if lot.state != "quarantine"
            else "This lot has no receipt details to correct.",
        )
        return redirect(lot_url)
    initial = {name: getattr(current, name) for name in services.RECEIPT_FIELDS}
    initial["quantity"] = current.quantity_text
    form = ReceiptCorrectionForm(request.POST or None, initial={**initial, "receipt": current.pk})
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["receipt"] != current.pk:
            form.add_error(None, services.RECEIPT_STALE)
        else:
            corrected = run(
                form,
                lambda: services.correct_receipt(
                    actor=request.user,
                    receipt=current,
                    reason=form.cleaned_data["reason"],
                    **form.receipt_values(),
                ),
            )
            if corrected:
                messages.success(request, "Receipt details corrected; the original is kept.")
                return redirect(lot_url)
    return receipt_page(
        request,
        form,
        title="Correct receipt details",
        crumbs=lot_crumbs(lot, "Correct receipt details"),
        cancel_url=lot_url,
        submit="Correct receipt details",
        intro="A correction adds a record and keeps the one it replaces. State what was wrong "
        "in the reason.",
        facts=lot_facts(lot),
    )


@login_required
def sample_new(request, pk):
    require_role(request.user, "analyst")
    lot = get_object_or_404(Lot, pk=pk)
    form = SampleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        sample = perform(
            form, lambda: services.add_sample(actor=request.user, lot=lot, **form.cleaned_data)
        )
        if sample:
            return redirect("quality:lot_detail", pk=lot.pk)
    return form_page(request, form, f"Add sample · {lot.number}", "Add sample")


@login_required
def result_new(request, pk):
    require_role(request.user, "analyst")
    sample = get_object_or_404(Sample.objects.select_related("lot"), pk=pk)
    form = ResultForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        result = perform(
            form,
            lambda: services.record_result(actor=request.user, sample=sample, **form.cleaned_data),
        )
        if result:
            return redirect("quality:lot_detail", pk=sample.lot_id)
    return form_page(request, form, f"Record result · {sample.reference}", "Record result")


@login_required
def sign(request, pk, action):
    is_review = action == "review"
    require_role(request.user, "reviewer" if is_review else "quality")
    obj = get_object_or_404(Result if is_review else Lot, pk=pk)
    lot = obj.sample.lot if is_review else obj
    form = SigningForm(request.POST or None, initial={"expected_revision": obj.revision})
    denial = "" if is_review else services.disposition_denial(request.user, obj)
    if not denial and request.method == "POST" and form.is_valid():
        signing_data = {k: v for k, v in form.cleaned_data.items() if k != "signature_username"}

        def commit():
            if is_review:
                services.review_result(actor=request.user, result=obj, **signing_data)
            else:
                services.dispose_lot(actor=request.user, lot=obj, **signing_data)
            return True

        if perform(form, commit):
            messages.success(request, "Signed review recorded." if is_review else "Lot released.")
            return redirect("quality:lot_detail", pk=lot.pk)
    return render(
        request,
        "signatures/sign.html",
        {
            "form": form,
            "lot": lot,
            "record": obj,
            "is_review": is_review,
            "meaning": "reviewed" if is_review else "approved",
            "denial": denial,
        },
        status=403 if denial else 422 if request.method == "POST" else 200,
    )
