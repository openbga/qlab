"""Calculated results, bench checks and raw-data files across apps.

Approved method with a calculation and resource requirements -> frozen requirement -> calculated
observation with the instrument and standard lot recorded -> review -> QC disposition ->
certificate. Uses the production requirement adapter and bench bridge and service-created
approvals only (synthetic data).
"""

import hashlib
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from analytical import gates
from analytical import services as analytical
from analytical.contracts import WorkRefused
from analytical.models import Observation, QCResult, RawDataFile
from catalog import services as catalog
from core.models import AuditEvent
from core.services import approve_rule, save_rule, set_pin
from laboratory import services as laboratory
from laboratory.eligibility import affected_uses
from laboratory.models import Qualification, ResourceUse
from quality import services as quality
from reporting import services as reporting
from sampling import services as sampling
from tests.receipts import on_site_receipt
from tests.test_integrated_journey import PASSWORD, PIN, approve, dispose

pytestmark = pytest.mark.django_db(transaction=True)

FORMULA = "titrant_volume * titer / sample_mass * 100"
INPUTS = [
    ("titrant_volume", "Titrant volume", "mL"),
    ("titer", "Titrant water equivalent", "mg/mL"),
    ("sample_mass", "Sample mass", "mg"),
]
# 1.25 * 4.98 / 2500.4 * 100 = 0.248960...; 1.31 * 4.98 / 2498.7 * 100 = 0.261087...
REPLICATES = [
    {"titrant_volume": "1.25", "titer": "4.98", "sample_mass": "2500.4"},
    {"titrant_volume": "1.31", "titer": "4.98", "sample_mass": "2498.7"},
]


def build_world(django_user_model):
    people = {}
    for name, roles in {
        "author": ["quality"],
        "approver": ["quality"],
        "analyst": ["analyst"],
        "reviewer": ["reviewer"],
    }.items():
        person = django_user_model.objects.create_user(
            username=f"cb_{name}", password=PASSWORD, first_name="Synthetic", last_name=name.title()
        )
        person.groups.add(*[Group.objects.get_or_create(name=r)[0] for r in roles])
        set_pin(actor=person, pin=PIN, password=PASSWORD)
        people[name] = person
    author, approver, analyst, reviewer = (
        people[name] for name in ("author", "approver", "analyst", "reviewer")
    )
    start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=365)
    window = {"effective_from": start, "effective_until": end}
    rules = save_rule(
        actor=author,
        code="synthetic-calculation-bench",
        segment="chemical",
        policy={
            "required_tests": ["water"],
            "review_meaning": "reviewed",
            "disposition_meaning": "approved",
        },
        reason="Synthetic policy",
        **window,
    )
    rules = approve_rule(
        actor=approver,
        pin=PIN,
        rule=rules,
        expected_revision=rules.revision,
        reason="Independent synthetic policy review",
    )
    material = catalog.create_material(
        actor=author,
        code="synthetic-cb-material",
        name="Synthetic calculated material",
        kind="raw_material",
        reason="Synthetic master data",
    )
    method, method_revision = catalog.create_method(
        actor=author,
        code="synthetic-kf",
        title="Synthetic water by titration",
        technique="Titration",
        document_ref="SOP-SYN-KF rev 1",
        suitability_kind="validation",
        suitability_ref="VAL-SYN-KF rev 1",
        requires_batch=False,
        requires_equipment=True,
        requires_reagent=True,
        reason="Synthetic calculated method",
        **window,
    )
    for code, name, unit in INPUTS:
        catalog.add_calculation_input(
            actor=author,
            revision=method_revision,
            code=code,
            name=name,
            unit=unit,
            reason="Synthetic raw measurement",
        )
    catalog.set_calculation(
        actor=author,
        revision=method_revision,
        formula=FORMULA,
        unit="% w/w",
        decimals=2,
        reason="Synthetic calculation",
    )
    approve(method_revision, approver)
    batch_method, batch_revision = catalog.create_method(
        actor=author,
        code="synthetic-lc",
        title="Synthetic batch method",
        technique="Chromatography",
        document_ref="SOP-SYN-LC rev 1",
        suitability_kind="validation",
        suitability_ref="VAL-SYN-LC rev 1",
        requires_batch=True,
        reason="Synthetic batch method",
        **window,
    )
    catalog.add_qc_check(
        actor=author,
        revision=batch_revision,
        code="control",
        name="Control standard recovery",
        unit="%",
        lower_limit=Decimal("98"),
        upper_limit=Decimal("102"),
        reason="Synthetic batch QC check",
    )
    approve(batch_revision, approver)
    _, spec = catalog.create_specification(
        actor=author,
        code="synthetic-cb-spec",
        title="Synthetic calculated specification",
        material=material,
        stage="incoming",
        scope="general",
        basis="Synthetic limits",
        reason="Synthetic specification",
        **window,
    )
    catalog.add_test_line(
        actor=author,
        revision=spec,
        reason="Synthetic line",
        method=method,
        required=True,
        replicates=2,
        max_retests=0,
        code="water",
        name="Water",
        result_type="numeric",
        unit="% w/w",
        upper_limit=Decimal("0.5"),
        upper_inclusive=True,
        reporting_decimals=1,
    )
    approve(spec, approver)
    _, plan = sampling.create_plan(
        actor=author,
        code="synthetic-cb-plan",
        title="Synthetic sampling plan",
        material=material,
        stage="incoming",
        basis="all",
        minimum_quantity=Decimal("10"),
        quantity_unit="g",
        instructions="Take one identified sample from each container.",
        rationale="Synthetic single-container lot only",
        reason="Synthetic sampling plan",
        **window,
    )
    approve(plan, approver)
    qualify(people, method.code)
    balance = laboratory.register_equipment(
        actor=analyst,
        asset_id="SYN-TITRATOR-01",
        description="Synthetic titrator",
        category="titrator",
        location="Synthetic laboratory",
        requires_qualification=False,
        reason="Synthetic equipment",
    )
    calibrate(people, balance)
    standard = receive_standard(people, "SYN-KF-TITRANT-01")
    lot = quality.receive_lot(
        actor=analyst,
        number="SYN-CB-001",
        material=material.name,
        rules=rules,
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )
    return {
        "people": people,
        "lot": lot,
        "material": material,
        "method": method,
        "equipment": balance,
        "standard": standard,
    }


def qualify(people, activity):
    qualification = laboratory.record_qualification(
        actor=people["author"],
        user=people["analyst"],
        activity=activity,
        evidence_ref=f"QUAL-{activity} rev 1",
        valid_from=timezone.localdate() - timedelta(days=1),
        valid_until=timezone.localdate() + timedelta(days=365),
        reason="Synthetic training evidence",
    )
    return laboratory.approve_qualification(
        actor=people["approver"],
        pin=PIN,
        qualification=qualification,
        expected_revision=qualification.revision,
        reason="Independent training evidence review",
    )


def calibrate(people, equipment, outcome="pass"):
    calibration = laboratory.record_calibration(
        actor=people["analyst"],
        equipment=equipment,
        performed_at=timezone.now() - timedelta(minutes=5),
        due_date=timezone.localdate() + timedelta(days=90),
        outcome=outcome,
        standard_ref="Synthetic certified standard SYN-CRM-1",
        reason="Synthetic calibration",
    )
    if outcome == "pass":
        laboratory.accept_calibration(
            actor=people["reviewer"],
            pin=PIN,
            calibration=calibration,
            expected_revision=calibration.revision,
            reason="Independent calibration review",
        )
    return calibration


def receive_standard(people, identifier, release=True):
    reagent = laboratory.receive_reagent(
        actor=people["analyst"],
        identifier=identifier,
        kind="reagent",
        name="Synthetic titrant",
        lot_number=f"LOT-{identifier}",
        received_on=timezone.localdate(),
        expiry_date=timezone.localdate() + timedelta(days=180),
        reason="Synthetic receipt",
    )
    if release:
        laboratory.release_reagent(
            actor=people["reviewer"],
            pin=PIN,
            reagent=reagent,
            expected_revision=reagent.revision,
            reason="Independent release review",
        )
        reagent.refresh_from_db()
    return reagent


@pytest.fixture
def world(django_user_model):
    return build_world(django_user_model)


def assign_water(data, reference="SYN-CB-S001"):
    analyst = data["people"]["analyst"]
    assignment = sampling.assign_requirements(
        actor=analyst,
        lot=data["lot"],
        material=data["material"],
        stage="incoming",
        reason="Assign approved synthetic policy",
    )
    assert assignment.status == "ready"
    sample = sampling.record_sampling(
        actor=analyst,
        lot=data["lot"],
        reference=reference,
        sampled_at=timezone.now(),
        containers_total=1,
        containers_sampled=1,
        container_ids="SYN-C001",
        quantity=Decimal("10"),
        quantity_unit="g",
        location="Synthetic sampling booth",
        reason="Synthetic controlled sampling",
    ).sample
    tests, holds = analytical.assign_tests(
        actor=analyst, sample=sample, reason="Assign frozen required tests"
    )
    assert holds == [], holds
    (test,) = tests
    return test


def record(data, test, inputs, **overrides):
    arguments = {
        "actor": data["people"]["analyst"],
        "test": test,
        "raw_reference": "RAW-SYN-CB rev 1",
        "inputs": inputs,
        "equipment_ids": [data["equipment"].pk],
        "reagent_ids": [data["standard"].pk],
        "reason": "Synthetic original observation",
    } | overrides
    observation = analytical.record_observation(**arguments)
    test.refresh_from_db()
    return observation


def blocked_events():
    return AuditEvent.objects.filter(action="resource.use_blocked")


def test_calculated_result_with_bench_evidence_to_issued_certificate(world):
    data, people = world, world["people"]
    test = assign_water(data)
    # The frozen requirement carries the approved calculation and the resource requirements.
    assert test.requirement["schema"] == "oq.test-requirement/3"
    method = test.requirement["method"]
    assert (method["requires_equipment"], method["requires_reagent"]) == (True, True)
    assert method["calculation"] == {
        "formula": FORMULA,
        "inputs": [{"code": c, "name": n, "unit": u} for c, n, u in INPUTS],
        "unit": "% w/w",
        "decimals": 2,
    }
    first = record(data, test, REPLICATES[0])
    second = record(data, test, REPLICATES[1])
    # Calculated from the inputs, rounded half-up to the approved decimals, inputs kept as entered.
    assert (first.value, first.value_text) == (Decimal("0.25"), "0.25")
    assert (second.value, second.value_text) == (Decimal("0.26"), "0.26")
    assert [(i["code"], i["value"], i["unit"]) for i in first.inputs] == [
        ("titrant_volume", "1.25", "mL"),
        ("titer", "4.98", "mg/mL"),
        ("sample_mass", "2500.4", "mg"),
    ]
    assert first.calculation == {
        "method": "synthetic-kf",
        "revision": 1,
        "formula": FORMULA,
        "unit": "% w/w",
        "decimals": 2,
    }
    # The bench evidence is frozen with the observation and matches the recorded uses.
    evidence = first.eligibility
    assert evidence["user"] == people["analyst"].pk and evidence["activity"] == "synthetic-kf"
    assert [e["asset_id"] for e in evidence["equipment"]] == ["SYN-TITRATOR-01"]
    assert [r["identifier"] for r in evidence["reagents"]] == ["SYN-KF-TITRANT-01"]
    uses = ResourceUse.objects.filter(
        context_type="analytical.analyticaltest", context_id=str(test.pk)
    )
    assert uses.count() == 4  # one instrument and one lot for each replicate
    assert {evidence["equipment"][0]["use"], evidence["reagents"][0]["use"]} <= set(
        uses.values_list("pk", flat=True)
    )
    assert set(uses.values_list("test_code", "activity")) == {("water", "synthetic-kf")}
    recorded = AuditEvent.objects.get(action="observation.recorded", after__replicate=1)
    assert recorded.after["inputs"] == first.inputs
    assert recorded.after["calculation"] == first.calculation
    assert recorded.after["eligibility"] == evidence

    test, investigation = analytical.submit_test(
        actor=people["analyst"],
        test=test,
        expected_revision=test.revision,
        reason="Submit synthetic observation",
    )
    assert investigation is None and test.conforms
    assert test.reportable_display == "0.3"  # mean 0.255 rounded half-up to one decimal
    analytical.review_test(
        actor=people["reviewer"],
        pin=PIN,
        test=test,
        expected_revision=test.revision,
        reason="Independent original-data review",
    )
    assert gates.lot_blockers(data["lot"]) == []
    lot = dispose(data, people["approver"])
    assert lot.state == "released"
    evidence, evidence_hash, blockers = reporting.preview(lot)
    assert blockers == [], blockers
    report = reporting.issue_report(
        actor=people["approver"],
        pin=PIN,
        lot=lot,
        recipient="Synthetic quality recipient",
        evidence_hash=evidence_hash,
        reason="Independent synthetic certificate issue",
    )
    version = report.versions.get(number=1)
    pdf = reporting.read_pdf(actor=people["reviewer"], version=version)
    assert hashlib.sha256(pdf).hexdigest() == version.pdf_sha256


def test_direct_value_and_bad_inputs_are_refused_for_a_calculated_method(world):
    data = world
    test = assign_water(data)
    revision = test.revision
    with pytest.raises(ValidationError, match="calculated from its inputs"):
        record(data, test, None, value=Decimal("0.25"))
    with pytest.raises(ValidationError, match="Sample mass"):
        record(data, test, {"titrant_volume": "1.25", "titer": "4.98"})
    with pytest.raises(ValidationError, match="divides by zero"):
        record(data, test, {**REPLICATES[0], "sample_mass": "0"})
    test.refresh_from_db()
    assert test.revision == revision
    assert not Observation.objects.filter(test=test).exists()
    assert not ResourceUse.objects.exists()


def test_missing_and_unfit_resources_refuse_the_entry_and_the_refusal_is_audited(world):
    data, people = world, world["people"]
    test = assign_water(data)
    data["lot"].refresh_from_db()
    revisions = (test.revision, data["lot"].revision)

    # The approved method requires an instrument and a lot: selecting none is refused.
    with pytest.raises(ValidationError, match="requires at least one instrument"):
        record(data, test, REPLICATES[0], equipment_ids=[])
    with pytest.raises(ValidationError, match="requires at least one reagent or standard lot"):
        record(data, test, REPLICATES[0], reagent_ids=[])
    assert not blocked_events().exists()

    # A lot that is not released is refused, and the refusal survives the rolled-back entry.
    unreleased = receive_standard(people, "SYN-KF-TITRANT-02", release=False)
    with pytest.raises(WorkRefused, match="SYN-KF-TITRANT-02: Lot has not been independently"):
        record(data, test, REPLICATES[0], reagent_ids=[unreleased.pk])
    event = blocked_events().get()
    assert event.actor_id == people["analyst"].pk
    assert event.after["context"] == f"analytical.analyticaltest:{test.pk}"
    assert event.after["refusals"][0]["subject"] == "SYN-KF-TITRANT-02"

    # Equipment taken out of service is refused.
    laboratory.take_out_of_service(
        actor=people["reviewer"], equipment=data["equipment"], reason="Synthetic fault found"
    )
    with pytest.raises(WorkRefused, match="SYN-TITRATOR-01: Equipment is out of service"):
        record(data, test, REPLICATES[0])
    assert blocked_events().count() == 2

    test.refresh_from_db()
    data["lot"].refresh_from_db()
    assert (test.revision, data["lot"].revision) == revisions
    assert not Observation.objects.filter(test=test).exists()
    assert not ResourceUse.objects.exists()


def test_revoked_qualification_refuses_the_entry(world):
    data, people = world, world["people"]
    test = assign_water(data)
    qualification = Qualification.objects.get(user=people["analyst"], activity="synthetic-kf")
    laboratory.revoke_qualification(
        actor=people["approver"],
        pin=PIN,
        qualification=qualification,
        expected_revision=qualification.revision,
        reason="Synthetic authorization withdrawn",
    )
    with pytest.raises(WorkRefused, match="No approved, current qualification"):
        record(data, test, REPLICATES[0])
    assert not Observation.objects.filter(test=test).exists()
    assert blocked_events().count() == 1


def test_batch_qc_needs_the_analyst_qualification_for_the_batch_method(world):
    data, people = world, world["people"]
    analyst = people["analyst"]
    batch = analytical.create_batch(
        actor=analyst, number="SYN-CB-B001", method_code="synthetic-lc", reason="Synthetic run"
    )
    entry = {
        "actor": analyst,
        "batch": batch,
        "check_code": "control",
        "value": Decimal("100.2"),
        "raw_reference": "RAW-SYN-CB-QC rev 1",
        "reason": "Synthetic batch QC",
    }
    # Qualified for the titration method only: batch QC for the other method is refused.
    with pytest.raises(WorkRefused, match="No approved, current qualification"):
        analytical.record_qc(**entry)
    assert not QCResult.objects.exists()
    event = blocked_events().get()
    assert event.after["context"] == f"analytical.qcbatch:{batch.pk}"
    assert event.after["activity"] == "synthetic-lc"

    qualification = qualify(people, "synthetic-lc")
    result = analytical.record_qc(**entry, equipment_ids=[data["equipment"].pk])
    assert result.eligibility["qualification"] == qualification.pk
    assert [e["asset_id"] for e in result.eligibility["equipment"]] == ["SYN-TITRATOR-01"]
    use = ResourceUse.objects.get()
    assert (use.context_type, use.context_id, use.test_code) == (
        "analytical.qcbatch",
        str(batch.pk),
        "control",
    )


def test_failed_calibration_lists_the_results_that_used_the_equipment(world, client):
    data, people = world, world["people"]
    test = assign_water(data)
    record(data, test, REPLICATES[0])
    equipment = data["equipment"]
    calibrate(people, equipment, outcome="fail")
    equipment.refresh_from_db()
    assert equipment.state == "out_of_service"
    affected = list(affected_uses(equipment))
    assert [(u.context_type, u.context_id) for u in affected] == [
        ("analytical.analyticaltest", str(test.pk))
    ]
    # The equipment page names the result, with a link to it, for the impact assessment.
    client.force_login(people["approver"])
    response = client.get(reverse("laboratory:equipment_detail", args=[equipment.pk]))
    assert response.status_code == 200
    body = response.content.decode()
    assert reverse("analytical:test_detail", args=[test.pk]) in body
    assert test.label in body and "SYN-CB-001" in body and "water" in body
    # The same instrument can no longer be recorded with a result.
    with pytest.raises(WorkRefused, match="SYN-TITRATOR-01"):
        record(data, test, REPLICATES[1])
    test.refresh_from_db()
    assert test.current_observations().count() == 1


def test_test_page_shows_how_the_value_was_calculated(world, client):
    data, people = world, world["people"]
    test = assign_water(data)
    record(data, test, REPLICATES[0])
    client.force_login(people["reviewer"])
    body = client.get(reverse("analytical:test_detail", args=[test.pk])).content.decode()
    flat = " ".join(body.split())
    for expected in (FORMULA, "Titrant volume", "2500.4", "SYN-TITRATOR-01", "SYN-KF-TITRANT-01"):
        assert expected in flat, expected


def test_raw_data_file_through_the_page_with_csrf_and_the_upload_limit(world, settings):
    data, people = world, world["people"]
    test = assign_water(data)
    url = reverse("analytical:raw_file_new", args=[test.pk])
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(people["analyst"])

    def post(content, description="Synthetic titration export"):
        token = browser.get(url).cookies["csrftoken"].value
        return browser.post(
            url,
            {
                "csrfmiddlewaretoken": token,
                "file": SimpleUploadedFile("titration-run-1.csv", content),
                "description": description,
            },
            follow=True,
        )

    payload = b"replicate,titrant_volume_mL\n1,1.25\n2,1.31\n"
    response = post(payload)
    assert response.status_code == 200, response.content.decode()[:500]
    stored = RawDataFile.objects.get(test=test)
    assert bytes(stored.content) == payload
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert stored.uploaded_by_id == people["analyst"].pk

    # A file above the limit is stopped while it is received, before the view could store it.
    settings.RAW_DATA_MAX_BYTES = 64
    response = post(b"x" * 4096, "Too large")
    assert "larger than the limit of 64 B. Nothing was stored." in response.content.decode()
    assert RawDataFile.objects.count() == 1

    reader = Client()
    reader.force_login(people["reviewer"])
    download = reader.get(reverse("analytical:raw_file_download", args=[stored.pk]))
    assert download.status_code == 200 and download.content == payload
    assert download["Content-Type"] == "application/octet-stream"
    assert download["X-Content-Type-Options"] == "nosniff"
    assert download["Content-Disposition"].startswith("attachment;")
