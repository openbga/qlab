"""Frozen catalog/sampling requirements, translated, parse with the analytical contract or hold."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from analytical.contracts import parse_method, parse_requirement
from catalog import services as catalog
from catalog.services import ApplicabilityHold
from catalog.tests.factories import (
    approve,
    approved_rules,
    count_line,
    material,
    numeric_line,
    qualitative_line,
    specification,
    window,
)
from quality.services import receive_lot
from sampling import services
from tests.receipts import on_site_receipt

from .test_services import plan_revision

pytestmark = pytest.mark.django_db(transaction=True)


def batch_method(people):
    start, end = window()
    _, revision = catalog.create_method(
        actor=people["author"],
        code="hplc-b",
        title="Batch HPLC",
        technique="HPLC",
        document_ref="SOP-SYN rev 1",
        suitability_kind="validation",
        suitability_ref="VAL-SYN",
        requires_batch=True,
        effective_from=start,
        effective_until=end,
        reason="Synthetic",
    )
    catalog.add_qc_check(
        actor=people["author"],
        revision=revision,
        reason="QC",
        code="blank",
        name="Blank",
        unit="%",
        upper_limit=Decimal("0.05"),
    )
    return approve(revision, people["approver"]).method


@pytest.fixture
def lot_with_requirements(people):
    mat = material(people["author"])
    hplc = batch_method(people)
    ident = approve(
        catalog.create_method(
            actor=people["author"],
            code="ftir-b",
            title="FTIR",
            technique="FTIR",
            document_ref="SOP rev 1",
            suitability_kind="validation",
            suitability_ref="VAL",
            effective_from=window()[0],
            effective_until=window()[1],
            reason="Synthetic",
        )[1],
        people["approver"],
    ).method
    _, spec = specification(people["author"], mat)
    qualitative_line(people["author"], spec, ident, code="identity")
    numeric_line(
        people["author"],
        spec,
        hplc,
        code="assay",
        reporting_decimals=1,
        replicates=2,
        max_retests=1,
    )
    numeric_line(
        people["author"],
        spec,
        hplc,
        code="impurity",
        low=None,
        high="0.5",
        upper_inclusive=False,
        reporting_decimals=2,
    )
    numeric_line(people["author"], spec, hplc, code="exact", reporting_decimals=None)
    count_line(people["author"], spec, hplc, code="tamc", high="100", reporting_decimals=0)
    qualitative_line(
        people["author"],
        spec,
        ident,
        code="salmonella",
        expected="Not detected in 25 g",
        outcome="absent",
    )
    numeric_line(people["author"], spec, hplc, code="info", reporting_decimals=1, required=False)
    approve(spec, people["approver"])
    approve(plan_revision(people["author"], mat), people["approver"])
    lot = receive_lot(
        actor=people["analyst"],
        number="SYN-B-1",
        material=mat.name,
        rules=approved_rules(people["author"]),
        reason="Synthetic",
        receipt=on_site_receipt(),
    )
    services.assign_requirements(
        actor=people["analyst"], lot=lot, material=mat, stage="incoming", reason="Assign"
    )
    return lot


def test_supported_tests_parse_and_unsupported_hold(people, lot_with_requirements):
    payloads = services.test_requirements(lot_with_requirements)
    assert set(payloads) == {"identity", "assay", "impurity", "exact", "tamc", "salmonella"}
    schemas = {code: payload["schema"] for code, payload in payloads.items()}
    assert schemas == {
        "assay": "oq.test-requirement/1",  # numeric with inclusive bounds stays v1
        "exact": "oq.test-requirement/1",
        "impurity": "oq.test-requirement/2",
        "tamc": "oq.test-requirement/2",
        "identity": "oq.test-requirement/2",
        "salmonella": "oq.test-requirement/2",
    }
    assay = parse_requirement(payloads["assay"])
    assert (assay.replicates, assay.reporting_decimals, assay.max_retests) == (2, 1, 1)
    assert assay.lower == Decimal("98") and assay.upper == Decimal("102")
    assert assay.method.requires_batch and assay.method.qc_checks[0].code == "blank"
    assert payloads["assay"]["source"].startswith("catalog:spec-api@v1#rev")
    assert parse_requirement(payloads["exact"]).reporting_decimals is None  # exact comparison
    impurity = parse_requirement(payloads["impurity"])
    assert impurity.upper == Decimal("0.5") and impurity.upper_inclusive is False
    tamc = parse_requirement(payloads["tamc"])
    assert (tamc.result_type, tamc.upper, tamc.unit) == ("count", Decimal("100"), "CFU/g")
    salmonella = parse_requirement(payloads["salmonella"])
    assert (salmonella.expected_result, salmonella.criterion) == (
        "absent",
        "Not detected in 25 g",
    )
    assert parse_requirement(payloads["identity"]).expected_result == "conforms"


def test_legacy_qualitative_line_translates_to_a_hold(people, lot_with_requirements):
    """A qualitative line frozen before outcomes existed has no expected_result key."""
    frozen = services.current_requirements(lot_with_requirements)
    identity = next(t for t in frozen["tests"] if t["code"] == "identity")
    legacy = {k: v for k, v in identity.items() if k != "expected_result"}
    payload = catalog.test_requirement(legacy, "catalog:legacy")
    assert payload["expected_result"] is None
    with pytest.raises(ValidationError):
        parse_requirement(payload)


def test_batch_methods_parse_in_analytical_contract(people):
    batch_method(people)
    [method] = catalog.batch_method_requirements()
    parsed = parse_method(method)
    assert parsed.requires_batch and parsed.revision == 1


def test_unassigned_lot_holds(people):
    lot = receive_lot(
        actor=people["analyst"],
        number="SYN-B-2",
        material="x",
        rules=approved_rules(people["author"]),
        reason="Synthetic",
        receipt=on_site_receipt(),
    )
    with pytest.raises(ApplicabilityHold):
        services.test_requirements(lot)


def test_source_changes_with_reassignment(people, lot_with_requirements):
    before = services.test_requirements(lot_with_requirements)["assay"]["source"]
    assignment = services.current_assignment(lot_with_requirements)
    services.assign_requirements(
        actor=people["analyst"],
        lot=lot_with_requirements,
        material=assignment.material,
        stage="incoming",
        reason="Reassign",
    )
    after = services.test_requirements(lot_with_requirements)["assay"]["source"]
    assert before != after  # each frozen assignment has its own hash (resolved_at differs)
