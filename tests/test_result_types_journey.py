"""Result types across apps: approved specification -> frozen tests -> review -> QC -> certificate.

Uses the production requirement adapter and service-created approvals only (synthetic data).
"""

import hashlib
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils import timezone

from analytical import gates
from analytical import services as analytical
from analytical.models import Investigation, Observation
from catalog import services as catalog
from core.services import approve_rule, save_rule, set_pin
from laboratory import services as laboratory
from quality import services as quality
from reporting import services as reporting
from sampling import services as sampling
from tests.receipts import on_site_receipt
from tests.test_integrated_journey import PASSWORD, PIN, approve, dispose

pytestmark = pytest.mark.django_db(transaction=True)

OBSERVED_ID = "Retention time and spectrum match the reference standard"
OBSERVED_SAL = "No Salmonella detected after enrichment of 25 g"
CODES = ["identity", "salmonella", "tamc", "impurity"]


def build_world(django_user_model, with_assay=False):
    people = {}
    for name, roles in {
        "author": ["quality"],
        "approver": ["quality"],
        "analyst": ["analyst", "quality", "reviewer"],
        "reviewer": ["reviewer"],
    }.items():
        person = django_user_model.objects.create_user(
            username=f"rt_{name}", password=PASSWORD, first_name="Synthetic", last_name=name.title()
        )
        person.groups.add(*[Group.objects.get_or_create(name=r)[0] for r in roles])
        set_pin(actor=person, pin=PIN, password=PASSWORD)
        people[name] = person
    author, approver = people["author"], people["approver"]
    start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=365)
    required = CODES + (["assay"] if with_assay else [])
    rules = save_rule(
        actor=author,
        code="synthetic-result-types",
        segment="chemical",
        policy={
            "required_tests": required,
            "review_meaning": "reviewed",
            "disposition_meaning": "approved",
        },
        effective_from=start,
        effective_until=end,
        reason="Synthetic policy",
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
        code="synthetic-rt-material",
        name="Synthetic result type material",
        kind="raw_material",
        reason="Synthetic master data",
    )
    method, method_revision = catalog.create_method(
        actor=author,
        code="synthetic-rt-method",
        title="Synthetic mixed-result method",
        technique="Gravimetry",
        document_ref="SOP-SYN-RT rev 1",
        suitability_kind="validation",
        suitability_ref="VAL-SYN-RT rev 1",
        requires_batch=False,
        effective_from=start,
        effective_until=end,
        reason="Explicit no-batch synthetic method",
    )
    approve(method_revision, approver)
    _, spec = catalog.create_specification(
        actor=author,
        code="synthetic-rt-spec",
        title="Synthetic result type specification",
        material=material,
        stage="incoming",
        scope="general",
        basis="Synthetic limits",
        effective_from=start,
        effective_until=end,
        reason="Synthetic specification",
    )
    common = {"method": method, "required": True, "replicates": 1, "max_retests": 0}
    lines = [
        {
            "code": "identity",
            "name": "Identity",
            "result_type": "qualitative",
            "expected_result": "conforms",
            "expected_text": "Conforms to the reference standard",
        },
        {
            "code": "salmonella",
            "name": "Salmonella",
            "result_type": "qualitative",
            "expected_result": "absent",
            "expected_text": "Absent in 25 g",
        },
        {
            "code": "tamc",
            "name": "Total aerobic count",
            "result_type": "count",
            "unit": "CFU/g",
            "upper_limit": Decimal("200"),
            "upper_inclusive": True,
        },
        {
            "code": "impurity",
            "name": "Impurity",
            "result_type": "numeric",
            "unit": "mg/g",
            "upper_limit": Decimal("5"),
            "upper_inclusive": False,
            "reporting_decimals": 2,
        },
    ]
    if with_assay:
        lines.append(
            {
                "code": "assay",
                "name": "Assay",
                "result_type": "numeric",
                "unit": "%",
                "lower_limit": Decimal("98"),
                "upper_limit": Decimal("102"),
                "lower_inclusive": True,
                "upper_inclusive": True,
                "reporting_decimals": 2,
            }
        )
    for line in lines:
        catalog.add_test_line(
            actor=author, revision=spec, reason="Synthetic line", **common, **line
        )
    spec = approve(spec, approver)
    _, plan = sampling.create_plan(
        actor=author,
        code="synthetic-rt-plan",
        title="Synthetic sampling plan",
        material=material,
        stage="incoming",
        basis="all",
        minimum_quantity=Decimal("10"),
        quantity_unit="g",
        instructions="Take one identified sample from each container.",
        rationale="Synthetic single-container lot only",
        effective_from=start,
        effective_until=end,
        reason="Synthetic sampling plan",
    )
    approve(plan, approver)
    qualification = laboratory.record_qualification(
        actor=author,
        user=people["analyst"],
        activity=method.code,
        evidence_ref="QUAL-SYN-RT rev 1",
        valid_from=start.date(),
        valid_until=end.date(),
        reason="Synthetic training evidence",
    )
    laboratory.approve_qualification(
        actor=approver,
        pin=PIN,
        qualification=qualification,
        expected_revision=qualification.revision,
        reason="Independent training evidence review",
    )
    lot = quality.receive_lot(
        actor=people["analyst"],
        number="SYN-RT-001",
        material=material.name,
        rules=rules,
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )
    return {"people": people, "lot": lot, "material": material, "spec": spec}


@pytest.fixture
def world(django_user_model):
    return build_world(django_user_model)


@pytest.fixture
def world_assay(django_user_model):
    return build_world(django_user_model, with_assay=True)


def assign_sample_tests(data):
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
        reference="SYN-RT-S001",
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
    return {t.test_code: t for t in tests}


def record(data, test, reading):
    """reading: an outcome code, "<10" (less than) or a plain number."""
    extra = {}
    if reading in {"conforms", "does_not_conform", "absent", "present"}:
        text = OBSERVED_ID if test.test_code == "identity" else OBSERVED_SAL
        extra = {"outcome": reading, "observed_text": text}
    elif reading.startswith("<"):
        extra = {"value": Decimal(reading[1:]), "qualifier": "<"}
    else:
        extra = {"value": Decimal(reading)}
    analytical.record_observation(
        actor=data["people"]["analyst"],
        test=test,
        raw_reference="RAW-SYN-RT rev 1",
        reason="Synthetic original observation",
        **extra,
    )
    test.refresh_from_db()


def submit(data, test):
    return analytical.submit_test(
        actor=data["people"]["analyst"],
        test=test,
        expected_revision=test.revision,
        reason="Submit synthetic observation",
    )


def review(data, test):
    test.refresh_from_db()
    return analytical.review_test(
        actor=data["people"]["reviewer"],
        pin=PIN,
        test=test,
        expected_revision=test.revision,
        reason="Independent original-data review",
    )


DEFAULT = {"identity": "conforms", "salmonella": "absent", "tamc": "<10", "impurity": "4.99"}


def run(data, **readings):
    """Assign, record and submit every required test; return {code: (test, investigation)}."""
    tests = assign_sample_tests(data)
    readings = {**DEFAULT, "assay": "100.25", **readings}
    out = {}
    for code, test in tests.items():
        record(data, test, readings[code])
        out[code] = submit(data, test)
    return out


def test_four_result_types_from_approval_to_issued_certificate(world):
    data, people = world, world["people"]
    submitted = run(data)
    assert {code: inv for code, (_, inv) in submitted.items()} == dict.fromkeys(CODES)
    assert not Investigation.objects.filter(lot=data["lot"]).exists()
    tests = {code: test for code, (test, _) in submitted.items()}
    # Frozen requirements: every shape here is v2 and carries the approved criterion text.
    for code, test in tests.items():
        assert test.requirement["schema"] == "oq.test-requirement/2", code
    assert tests["identity"].requirement["expected_result"] == "conforms"
    assert tests["salmonella"].requirement["criterion"] == "Absent in 25 g"
    assert tests["impurity"].requirement["upper_inclusive"] is False
    # The less-than reading is stored as recorded and never becomes zero or a number.
    tamc = tests["tamc"]
    observation = tamc.current_observations().get()
    assert (observation.qualifier, observation.value, observation.value_text) == (
        "<",
        Decimal("10"),
        "<10",
    )
    assert not Observation.objects.filter(test=tamc, value=0).exists()
    assert (tamc.mean_value, tamc.reportable_value) == (None, None)
    assert tamc.reportable_text == "<10" and tamc.conforms
    assert tests["identity"].reportable_text == "Conforms"
    assert tests["salmonella"].reportable_text == "Absent"
    assert tests["impurity"].reportable_display == "4.99"
    assert all(t.conforms for t in tests.values())
    for test in tests.values():
        review(data, test)
    assert gates.lot_blockers(data["lot"]) == []
    lot = dispose(data, people["approver"])
    assert lot.state == "released"
    results = {r["test_code"]: r for r in lot.disposition_evidence["analytical"]["results"]}
    assert set(results) == set(CODES)
    assert results["tamc"]["replicates"][0]["value"] == "<10"
    assert results["tamc"]["mean"] is None and results["tamc"]["reportable"] == "<10"
    assert results["tamc"]["acceptance"] == "at most 200 CFU/g"
    assert results["identity"]["replicates"][0]["observed"] == OBSERVED_ID
    assert results["identity"]["replicates"][0]["value"] == "Conforms"
    assert results["identity"]["mean"] is None
    assert results["salmonella"]["replicates"][0]["observed"] == OBSERVED_SAL
    assert results["salmonella"]["reportable"] == "Absent"
    assert results["salmonella"]["acceptance"] == "Absent in 25 g (expected: Absent)"
    assert results["impurity"]["acceptance"] == "less than 5 mg/g"
    assert results["impurity"]["upper_inclusive"] is False
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
    html = render_to_string("reporting/_certificate.html", {"snapshot": version.snapshot})
    flat = " ".join(html.split())
    assert "<td>&lt;10</td>" in flat and "None" not in html
    assert "at most 200 CFU/g" in flat and "less than 5 mg/g" in flat
    assert "Absent in 25 g (expected: Absent)" in flat
    assert "Conforms to the reference standard (expected: Conforms)" in flat
    pdf = reporting.read_pdf(actor=people["reviewer"], version=version)
    assert hashlib.sha256(pdf).hexdigest() == version.pdf_sha256
    from reporting.tests.test_services import normalized, pdf_text

    spoken = normalized(pdf_text(pdf))
    for phrase in ("<10 CFU/g", "Absent", "Conforms", "at most 200 CFU/g", "less than 5 mg/g"):
        assert phrase in spoken, phrase
    assert "None" not in spoken


def assert_blocked_by_investigation(data, code, submitted):
    test, investigation = submitted[code]
    assert not test.conforms
    assert investigation is not None
    assert Investigation.objects.filter(lot=data["lot"], test=test).exists()
    for other, (t, _) in submitted.items():
        if other != code:
            review(data, t)
    assert gates.lot_blockers(data["lot"])
    with pytest.raises(ValidationError):
        dispose(data, data["people"]["approver"])
    data["lot"].refresh_from_db()
    assert data["lot"].state == "quarantine"


def test_value_on_exclusive_bound_does_not_conform(world):
    submitted = run(world, impurity="5")
    assert submitted["impurity"][0].reportable_display == "5.00"
    assert_blocked_by_investigation(world, "impurity", submitted)


def test_present_on_expected_absent_line_opens_investigation(world):
    submitted = run(world, salmonella="present")
    assert submitted["salmonella"][0].reportable_text == "Present"
    assert_blocked_by_investigation(world, "salmonella", submitted)


def test_less_than_above_upper_limit_does_not_pass(world):
    submitted = run(world, tamc="<250")
    test = submitted["tamc"][0]
    assert test.reportable_text == "<250" and test.mean_value is None
    assert_blocked_by_investigation(world, "tamc", submitted)


def test_less_than_at_inclusive_limit_passes(world):
    submitted = run(world, tamc="<200")
    assert submitted["tamc"][0].conforms and submitted["tamc"][1] is None


def test_inclusive_numeric_still_freezes_v1_others_v2(world_assay):
    tests = assign_sample_tests(world_assay)
    assert tests["assay"].requirement["schema"] == "oq.test-requirement/1"
    for code in CODES:
        assert tests[code].requirement["schema"] == "oq.test-requirement/2", code
    record(world_assay, tests["assay"], "100.25")
    test, investigation = submit(world_assay, tests["assay"])
    assert investigation is None and test.conforms
    assert test.requirement["schema"] == "oq.test-requirement/1"


def test_recorder_cannot_review_a_qualitative_test(world):
    tests = assign_sample_tests(world)
    test = tests["identity"]
    record(world, test, "conforms")
    test, _ = submit(world, test)
    analyst = world["people"]["analyst"]  # also holds the reviewer role
    with pytest.raises(ValidationError, match="own"):
        analytical.review_test(
            actor=analyst,
            pin=PIN,
            test=test,
            expected_revision=test.revision,
            reason="Self review denied",
        )
    test.refresh_from_db()
    assert test.state == "submitted"
