"""Cross-package acceptance using approved service-created policy, never fixture providers."""

import hashlib
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.urls import reverse
from django.utils import timezone

from analytical import gates
from analytical import services as analytical
from catalog import services as catalog
from core.models import ElectronicSignature
from core.services import approve_rule, save_rule, set_pin
from laboratory import services as laboratory
from quality import services as quality
from quality.models import Result
from reporting import services as reporting
from reporting.models import ReportVersion
from sampling import services as sampling
from sampling.models import SamplingRecord
from tests.receipts import on_site_receipt

pytestmark = pytest.mark.django_db(transaction=True)
PIN = "84621357"
PASSWORD = "Synthetic-integration-login-2026!"


def approve(revision, actor):
    revision.refresh_from_db()
    return catalog.approve_revision(
        actor=actor,
        pin=PIN,
        revision=revision,
        expected_revision=revision.revision,
        reason="Independent synthetic configuration review",
    )


@pytest.fixture
def integrated(django_user_model, settings):
    # This is the production adapter. No analytical.fixtures or approval-row shortcuts.
    assert settings.ANALYTICAL_REQUIREMENT_PROVIDER == (
        "config.integrations.CatalogRequirementProvider"
    )
    people = {}
    for name, roles in {
        "author": ["quality"],
        "approver": ["quality"],
        "analyst": ["analyst", "quality", "reviewer"],
        "reviewer": ["reviewer"],
        # Receives the lot, so "analyst" is never barred from disposition as a receipt author
        # and the sampling and test-data rules are exercised on their own.
        "receiver": ["analyst"],
    }.items():
        person = django_user_model.objects.create_user(
            username=f"synthetic_{name}",
            password=PASSWORD,
            first_name="Synthetic",
            last_name=name.title(),
        )
        person.groups.add(*[Group.objects.get_or_create(name=r)[0] for r in roles])
        set_pin(actor=person, pin=PIN, password=PASSWORD)
        people[name] = person
    author, approver = people["author"], people["approver"]
    start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=365)
    rules = save_rule(
        actor=author,
        code="synthetic-integrated",
        segment="chemical",
        policy={
            "required_tests": ["assay"],
            "review_meaning": "reviewed",
            "disposition_meaning": "approved",
        },
        effective_from=start,
        effective_until=end,
        reason="Synthetic integration policy",
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
        code="synthetic-powder",
        name="Synthetic reference powder",
        kind="raw_material",
        reason="Synthetic master data",
    )
    method, method_revision = catalog.create_method(
        actor=author,
        code="synthetic-assay",
        title="Synthetic assay",
        technique="Gravimetry",
        document_ref="SOP-SYN-001 rev 1",
        suitability_kind="validation",
        suitability_ref="VAL-SYN-001 rev 1",
        requires_batch=False,
        effective_from=start,
        effective_until=end,
        reason="Explicit no-batch synthetic method",
    )
    method_revision = approve(method_revision, approver)
    _, spec_revision = catalog.create_specification(
        actor=author,
        code="synthetic-spec",
        title="Synthetic incoming specification",
        material=material,
        stage="incoming",
        scope="general",
        basis="Synthetic test limits",
        effective_from=start,
        effective_until=end,
        reason="Synthetic specification",
    )
    catalog.add_test_line(
        actor=author,
        revision=spec_revision,
        reason="Synthetic numeric assay",
        code="assay",
        name="Assay",
        method=method,
        result_type="numeric",
        unit="%",
        lower_limit=Decimal("98"),
        upper_limit=Decimal("102"),
        lower_inclusive=True,
        upper_inclusive=True,
        reporting_decimals=2,
        replicates=1,
        replicate_limits=True,
        max_retests=0,
        required=True,
    )
    spec_revision = approve(spec_revision, approver)
    _, plan_revision = sampling.create_plan(
        actor=author,
        code="synthetic-plan",
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
    plan_revision = approve(plan_revision, approver)
    qualification = laboratory.record_qualification(
        actor=author,
        user=people["analyst"],
        activity=method.code,
        evidence_ref="QUAL-SYN-001 rev 1",
        valid_from=start.date(),
        valid_until=end.date(),
        reason="Synthetic analyst training evidence",
    )
    qualification = laboratory.approve_qualification(
        actor=approver,
        pin=PIN,
        qualification=qualification,
        expected_revision=qualification.revision,
        reason="Independent training evidence review",
    )
    lot = quality.receive_lot(
        actor=people["receiver"],
        number="SYN-INTEGRATED-001",
        material=material.name,
        rules=rules,
        reason="Synthetic integrated receipt",
        receipt=on_site_receipt(),
    )
    return {
        "people": people,
        "lot": lot,
        "material": material,
        "method": method_revision,
        "spec": spec_revision,
        "plan": plan_revision,
        "qualification": qualification,
    }


def assign_and_sample(data):
    actor = data["people"]["analyst"]
    assignment = sampling.assign_requirements(
        actor=actor,
        lot=data["lot"],
        material=data["material"],
        stage="incoming",
        reason="Assign approved synthetic policy",
    )
    assert assignment.status == "ready"
    record = sampling.record_sampling(
        actor=actor,
        lot=data["lot"],
        reference="SYN-INTEGRATED-S001",
        sampled_at=timezone.now(),
        containers_total=1,
        containers_sampled=1,
        container_ids="SYN-C001",
        quantity=Decimal("10"),
        quantity_unit="g",
        location="Synthetic sampling booth",
        reason="Synthetic controlled sampling",
    )
    return record.sample


def observed_test(data, sample, value):
    tests, holds = analytical.assign_tests(
        actor=data["people"]["analyst"],
        sample=sample,
        reason="Assign frozen required tests",
    )
    assert holds == [], holds
    assert len(tests) == 1
    test = tests[0]
    assignment = sampling.current_assignment(data["lot"])
    spec = data["spec"]
    assert assignment.specification_revision_id == spec.pk
    assert assignment.payload_hash == catalog.digest(assignment.payload)
    assert test.requirement["source"] == (
        f"catalog:{spec.specification.code}@v{spec.version}#rev{spec.pk}"
        f"/lot-req:{assignment.payload_hash[:16]}"
    )
    assert test.requirement["method"]["requires_batch"] is False
    analytical.record_observation(
        actor=data["people"]["analyst"],
        test=test,
        value=Decimal(value),
        raw_reference="RAW-SYN-001 rev 1",
        reason="Synthetic original observation",
    )
    test.refresh_from_db()
    return analytical.submit_test(
        actor=data["people"]["analyst"],
        test=test,
        expected_revision=test.revision,
        reason="Submit synthetic observation",
    )


def dispose(data, actor):
    lot = data["lot"]
    lot.refresh_from_db()
    return quality.dispose_lot(
        actor=actor,
        pin=PIN,
        lot=lot,
        expected_revision=lot.revision,
        reason="Synthetic independent QC disposition",
    )


def test_approved_catalog_to_native_review_disposition_and_immutable_pdf(integrated):
    data, people = integrated, integrated["people"]
    sample = assign_and_sample(data)
    test, investigation = observed_test(data, sample, "100.25")
    assert investigation is None
    with pytest.raises(ValidationError, match="own"):
        analytical.review_test(
            actor=people["analyst"],
            pin=PIN,
            test=test,
            expected_revision=test.revision,
            reason="Self review denied",
        )
    test = analytical.review_test(
        actor=people["reviewer"],
        pin=PIN,
        test=test,
        expected_revision=test.revision,
        reason="Independent original-data review",
    )
    assert gates.lot_blockers(data["lot"]) == []
    assert people["analyst"].pk in gates.lot_author_ids(data["lot"])
    assert not Result.objects.filter(sample__lot=data["lot"]).exists()
    with pytest.raises((PermissionDenied, ValidationError), match="own|author"):
        dispose(data, people["analyst"])
    lot = dispose(data, people["approver"])
    assert lot.state == "released"
    assert lot.disposition_evidence["assignment_hash"]
    assert lot.disposition_evidence["analytical"]["blockers"] == []
    evidence, evidence_hash, blockers = reporting.preview(lot)
    assert blockers == [], blockers
    assert "100.25" in str(evidence)
    assert data["spec"].approved_hash in str(evidence)
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
    assert pdf.startswith(b"%PDF-") and hashlib.sha256(pdf).hexdigest() == version.pdf_sha256
    signature = reporting.signature_for(version)
    assert signature.signed_at == version.issued_at
    assert signature.content["current_pdf_sha256"] == version.pdf_sha256
    assert ElectronicSignature.objects.filter(
        object_type="analytical.analyticaltest", object_id=str(test.pk)
    ).exists()
    with pytest.raises(DatabaseError), transaction.atomic():
        ReportVersion.objects.filter(pk=version.pk).update(pdf=b"changed")
    version.refresh_from_db()
    assert reporting.read_pdf(actor=people["reviewer"], version=version) == pdf


def test_oos_native_evidence_cannot_be_bypassed_by_legacy_results(integrated, settings):
    data, people = integrated, integrated["people"]
    # Historical development-only foundation data exists before native policy is assigned.
    # It must never become a substitute for the native result/investigation after assignment.
    settings.DEBUG = True
    sample = quality.add_sample(
        actor=people["analyst"],
        lot=data["lot"],
        reference="SYN-LEGACY-S001",
        collected_at=timezone.now(),
        reason="Synthetic historical foundation sample",
    )
    legacy = quality.record_result(
        actor=people["analyst"],
        sample=sample,
        test_code="assay",
        value=Decimal("100"),
        unit="%",
        lower_limit=Decimal("98"),
        upper_limit=Decimal("102"),
        reason="Synthetic historical foundation result",
    )
    quality.review_result(
        actor=people["reviewer"],
        pin=PIN,
        result=legacy,
        expected_revision=legacy.revision,
        reason="Synthetic legacy review",
    )
    assignment = sampling.assign_requirements(
        actor=people["analyst"],
        lot=data["lot"],
        material=data["material"],
        stage="incoming",
        reason="Adopt approved native requirements",
    )
    assert assignment.status == "ready"
    test, investigation = observed_test(data, sample, "90")
    assert investigation is not None and not test.conforms
    assert gates.lot_blockers(data["lot"])
    with pytest.raises(ValidationError):
        dispose(data, people["approver"])
    data["lot"].refresh_from_db()
    assert data["lot"].state == "quarantine"
    assert not ElectronicSignature.objects.filter(
        object_type="quality.lot", object_id=str(data["lot"].pk)
    ).exists()
    assert reporting.preview(data["lot"])[2]


def test_each_native_sample_requires_its_own_reviewed_results(integrated):
    data, people = integrated, integrated["people"]
    first = assign_and_sample(data)
    test, _ = observed_test(data, first, "100")
    analytical.review_test(
        actor=people["reviewer"],
        pin=PIN,
        test=test,
        expected_revision=test.revision,
        reason="Independent first-sample review",
    )
    second = sampling.record_sampling(
        actor=people["analyst"],
        lot=data["lot"],
        reference="SYN-INTEGRATED-S002",
        sampled_at=timezone.now(),
        containers_total=1,
        containers_sampled=1,
        container_ids="SYN-C001",
        quantity=Decimal("10"),
        quantity_unit="g",
        location="Synthetic sampling booth",
        reason="Second independent synthetic sample",
    ).sample
    problems = gates.lot_blockers(data["lot"])
    assert any(second.reference in problem for problem in problems)
    with pytest.raises(ValidationError, match=second.reference):
        dispose(data, people["approver"])
    data["lot"].refresh_from_db()
    assert data["lot"].state == "quarantine"


def test_holds_block_disposition_and_post_release_certificate(integrated):
    from stability import services as stability

    sample = assign_and_sample(integrated)
    test, _ = observed_test(integrated, sample, "100")
    analytical.review_test(
        actor=integrated["people"]["reviewer"],
        pin=PIN,
        test=test,
        expected_revision=test.revision,
        reason="Independent check",
    )
    hold = stability.place_hold(
        actor=integrated["people"]["analyst"],
        lot=integrated["lot"],
        kind="quality",
        reason="Synthetic quality hold",
    )
    with pytest.raises(ValidationError, match="hold"):
        dispose(integrated, integrated["people"]["approver"])
    stability.release_hold(
        actor=integrated["people"]["approver"],
        pin=PIN,
        hold=hold,
        expected_revision=hold.revision,
        reason="Independent hold resolution",
    )
    lot = dispose(integrated, integrated["people"]["approver"])
    stability.place_hold(
        actor=integrated["people"]["analyst"],
        lot=lot,
        kind="quality",
        reason="New post-release evidence",
    )
    _, _, problems = reporting.preview(lot)
    assert any("hold" in problem.lower() for problem in problems)


def test_native_results_cannot_replace_sampling_provenance(integrated):
    data, people = integrated, integrated["people"]
    sampling.assign_requirements(
        actor=people["analyst"],
        lot=data["lot"],
        material=data["material"],
        stage="incoming",
        reason="Approved requirement assignment",
    )
    sample = quality.add_sample(
        actor=people["analyst"],
        lot=data["lot"],
        reference="SYN-UNPROVEN-SAMPLE",
        collected_at=timezone.now(),
        reason="Basic receipt alone is not sampling-plan evidence",
    )
    test, _ = observed_test(data, sample, "100")
    analytical.review_test(
        actor=people["reviewer"],
        pin=PIN,
        test=test,
        expected_revision=test.revision,
        reason="Review result only",
    )
    assert gates.lot_blockers(data["lot"]) == []
    with pytest.raises(ValidationError, match="no sampling record"):
        dispose(data, people["approver"])


def test_revoked_method_qualification_blocks_native_observation(integrated, settings):
    data, people = integrated, integrated["people"]
    assert settings.ANALYTICAL_BENCH == "config.integrations.LaboratoryBench"
    sample = assign_and_sample(data)
    tests, holds = analytical.assign_tests(
        actor=people["analyst"],
        sample=sample,
        reason="Assign test while analyst is qualified",
    )
    assert holds == [] and len(tests) == 1
    test = tests[0]
    qualification = data["qualification"]
    assert qualification.state == "approved"
    assert qualification.activity == test.spec.method.code
    revoked = laboratory.revoke_qualification(
        actor=people["approver"],
        pin=PIN,
        qualification=qualification,
        expected_revision=qualification.revision,
        reason="Synthetic method authorization withdrawn before observation",
    )
    assert revoked.state == "revoked" and revoked.revoked_at
    data["lot"].refresh_from_db()
    lot_revision, test_revision = data["lot"].revision, test.revision
    with pytest.raises(ValidationError, match="No approved, current qualification"):
        analytical.record_observation(
            actor=people["analyst"],
            test=test,
            value=Decimal("100"),
            raw_reference="RAW-SYN-BLOCKED-001",
            reason="Attempt after qualification revoked",
        )
    test.refresh_from_db()
    data["lot"].refresh_from_db()
    assert test.revision == test_revision
    assert data["lot"].revision == lot_revision
    assert not test.current_observations().exists()


def sampling_author(data, username):
    """Another analyst who also holds quality: multiple roles never waive independence."""
    person = type(data["people"]["analyst"]).objects.create_user(
        username=username, password=PASSWORD, first_name="Synthetic", last_name="Sampler"
    )
    person.groups.add(*Group.objects.filter(name__in=["analyst", "quality"]))
    set_pin(actor=person, pin=PIN, password=PASSWORD)
    return person


def reviewed_lot(data, sample):
    test, _ = observed_test(data, sample, "100.25")
    analytical.review_test(
        actor=data["people"]["reviewer"],
        pin=PIN,
        test=test,
        expected_revision=test.revision,
        reason="Independent original-data review",
    )
    assert gates.lot_blockers(data["lot"]) == []


def assert_self_disposition_refused(client, data, person):
    client.force_login(person)
    page = client.get(reverse("quality:disposition", args=[data["lot"].pk]))
    assert page.status_code == 403
    assert b"own receipt, sampling or test data" in page.content
    assert b'name="pin"' not in page.content  # Explained before any PIN is requested.
    with pytest.raises(ValidationError, match="own receipt, sampling or test data"):
        dispose(data, person)
    data["lot"].refresh_from_db()
    assert data["lot"].state == "quarantine"
    assert not ElectronicSignature.objects.filter(
        object_type="quality.lot", object_id=str(data["lot"].pk)
    ).exists()


def sampled_by(data, sampler):
    """Assign the requirements and let ``sampler`` take and record the sample."""
    sampling.assign_requirements(
        actor=data["people"]["analyst"],
        lot=data["lot"],
        material=data["material"],
        stage="incoming",
        reason="Assign approved synthetic policy",
    )
    return sampling.record_sampling(
        actor=sampler,
        lot=data["lot"],
        reference="SYN-INDEPENDENCE-S001",
        sampled_at=timezone.now(),
        containers_total=1,
        containers_sampled=1,
        container_ids="SYN-C001",
        quantity=Decimal("10"),
        quantity_unit="g",
        location="Synthetic sampling booth",
        reason="Synthetic controlled sampling",
    ).sample


def test_sampler_with_quality_role_cannot_sign_disposition(integrated, client):
    data, people = integrated, integrated["people"]
    sampler = sampling_author(data, "synthetic_sampler")
    reviewed_lot(data, sampled_by(data, sampler))
    assert sampler.pk not in gates.lot_author_ids(data["lot"])  # Not an analytical author.
    assert sampler.pk not in quality.receipt_author_ids(data["lot"])  # Nor a receipt author.
    assert_self_disposition_refused(client, data, sampler)
    assert dispose(data, people["approver"]).state == "released"


def test_analyst_who_only_tested_cannot_sign_disposition(integrated, client):
    """Authorship of test data alone bars disposition: others received and sampled the lot."""
    data, people = integrated, integrated["people"]
    analyst = people["analyst"]  # Also holds the quality role; that never waives the rule.
    reviewed_lot(data, sampled_by(data, sampling_author(data, "synthetic_sampler")))
    assert analyst.pk in gates.lot_author_ids(data["lot"])
    assert analyst.pk not in sampling.lot_author_ids(data["lot"])
    assert analyst.pk not in quality.receipt_author_ids(data["lot"])
    assert_self_disposition_refused(client, data, analyst)
    assert dispose(data, people["approver"]).state == "released"


def test_receipt_corrector_with_quality_role_cannot_sign_disposition(integrated, client):
    data, people = integrated, integrated["people"]
    corrector = sampling_author(data, "synthetic_recounter")
    quality.correct_receipt(
        actor=corrector,
        receipt=quality.current_receipt(data["lot"]),
        reason="Synthetic recount of the delivery",
        **on_site_receipt(containers=2),
    )
    data["lot"].refresh_from_db()
    reviewed_lot(data, assign_and_sample(data))
    assert corrector.pk not in gates.lot_author_ids(data["lot"])  # Not an analytical author.
    assert corrector.pk not in sampling.lot_author_ids(data["lot"])  # Nor a sampling author.
    assert_self_disposition_refused(client, data, corrector)
    assert dispose(data, people["approver"]).state == "released"


def test_sampling_corrector_with_quality_role_cannot_sign_disposition(integrated, client):
    data, people = integrated, integrated["people"]
    corrector = sampling_author(data, "synthetic_corrector")
    sample = assign_and_sample(data)
    original = SamplingRecord.objects.get(sample=sample)
    sampling.correct_sampling(
        actor=corrector,
        record=original,
        reason="Synthetic transcription correction",
        sampled_at=original.sampled_at,
        containers_total=1,
        containers_sampled=1,
        container_ids="SYN-C001",
        quantity=Decimal("12"),
        quantity_unit="g",
        location="Synthetic sampling booth",
    )
    reviewed_lot(data, sample)
    assert_self_disposition_refused(client, data, corrector)
    assert dispose(data, people["approver"]).state == "released"


def test_sample_creation_and_hold_release_by_same_account_do_not_deadlock(integrated, monkeypatch):
    """A sample's deferred actor FK must not cycle with signing's account-before-lot locks."""
    from laboratory.tests.helpers import run_interleaved
    from quality.models import Sample
    from stability import services as stability
    from stability.models import Hold

    lot, people = integrated["lot"], integrated["people"]
    actor = people["analyst"]  # Also holds quality; independent of the hold placer.
    hold = stability.place_hold(
        actor=people["approver"], lot=lot, kind="quality", reason="Synthetic independent hold"
    )
    outcome = run_interleaved(
        monkeypatch,
        quality,
        "record_event",
        lambda: quality.add_sample(
            actor=actor,
            lot=lot,
            reference="SYN-CONCURRENT-SAMPLE",
            collected_at=timezone.now(),
            reason="Synthetic sample during hold review",
        ),
        lambda: stability.release_hold(
            actor=actor,
            pin=PIN,
            hold=hold,
            expected_revision=hold.revision,
            reason="Synthetic independent hold release",
        ),
    )
    assert isinstance(outcome["first"], Sample), outcome
    assert isinstance(outcome["second"], Hold), outcome
    hold.refresh_from_db()
    assert hold.state == Hold.State.RELEASED
    assert Sample.objects.get(reference="SYN-CONCURRENT-SAMPLE").created_by == actor
    assert (
        ElectronicSignature.objects.filter(
            object_type="stability.hold", object_id=str(hold.pk), signer=actor
        ).count()
        == 1
    )
