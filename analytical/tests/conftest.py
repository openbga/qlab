import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from analytical import fixtures, services
from core.models import RuleSet
from core.services import set_pin
from quality.services import add_sample, receive_lot
from tests.receipts import on_site_receipt

PIN = "24681357"
PASSWORD = "synthetic-pass-2026"
FIXTURES = "analytical.fixtures.FixtureProvider"
BENCH = "analytical.fixtures.SyntheticBench"


@pytest.fixture(autouse=True)
def fixture_provider(settings):
    """Synthetic requirements and bench are explicit test overrides, never deployment defaults."""
    settings.ANALYTICAL_REQUIREMENT_PROVIDER = FIXTURES
    settings.ANALYTICAL_BENCH = BENCH
    fixtures.BENCH_LOG.clear()
    fixtures.UNQUALIFIED.clear()
    yield
    fixtures.BENCH_LOG.clear()
    fixtures.UNQUALIFIED.clear()


@pytest.fixture
def people(django_user_model):
    found = {}
    for name, roles in {
        "analyst": ["analyst"],
        "analyst2": ["analyst"],
        "reviewer": ["reviewer"],
        "reviewer2": ["reviewer"],
        "quality": ["quality"],
        "quality2": ["quality"],
        "auditor": ["auditor"],
        "multi": ["analyst", "reviewer", "quality"],
    }.items():
        user = django_user_model.objects.create_user(
            name, password=PASSWORD, first_name="Test", last_name=name.capitalize()
        )
        for role in roles:
            user.groups.add(Group.objects.get_or_create(name=role)[0])
        set_pin(actor=user, pin=PIN, password=PASSWORD)
        found[name] = user
    return found


@pytest.fixture
def make_lot(people):
    def make(number="SYN-LOT-1", tests=("assay", "identity")):
        rules = RuleSet.objects.create(
            code=f"syn-{number.lower()}",
            segment="chemical",
            author=people["quality"],
            status="approved",
            effective_from=timezone.now() - timedelta(days=1),
            effective_until=timezone.now() + timedelta(days=365),
            policy={
                "required_tests": list(tests),
                "review_meaning": "reviewed",
                "disposition_meaning": "approved",
            },
        )
        lot = receive_lot(
            actor=people["analyst"],
            number=number,
            material="Synthetic powder",
            rules=rules,
            reason="Synthetic receipt",
            receipt=on_site_receipt(),
        )
        sample = add_sample(
            actor=people["analyst"],
            lot=lot,
            reference=f"{number}-S1",
            collected_at=timezone.now(),
            reason="Synthetic sample",
        )
        return lot, sample

    return make


@pytest.fixture
def lot_sample(make_lot):
    return make_lot()


@pytest.fixture
def assigned(people, lot_sample):
    lot, sample = lot_sample
    created, holds = services.assign_tests(
        actor=people["analyst"], sample=sample, reason="Required tests"
    )
    assert holds == []
    return lot, sample, {t.test_code: t for t in created}


@pytest.fixture
def batch(people):
    return services.create_batch(
        actor=people["analyst2"], number="SYN-B1", method_code="SYN-HPLC", reason="Run"
    )


@pytest.fixture
def plain_static(settings):
    # Template tests must not depend on a collected manifest in the shared static directory.
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


def login(client, user):
    client.force_login(user)
    session = client.session
    session["authenticated_at"] = session["last_activity_at"] = time.time()
    session.save()
    return client


def fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def pass_qc(people, batch, control="100.0"):
    services.record_qc(
        actor=people["analyst2"],
        batch=batch,
        check_code="blank",
        value=Decimal("0.01"),
        raw_reference="RUN-1 blank",
    )
    services.record_qc(
        actor=people["analyst2"],
        batch=batch,
        check_code="control",
        value=Decimal(control),
        raw_reference="RUN-1 control",
    )


def record(people, test, *values, who="analyst"):
    for value in values:
        services.record_observation(
            actor=people[who], test=test, value=Decimal(value), raw_reference="NB-1 p1"
        )
    return fresh(test)


def submit(people, test, who="analyst"):
    test = fresh(test)
    return services.submit_test(
        actor=people[who], test=test, expected_revision=test.revision, reason="Complete"
    )


def review(people, test, who="reviewer"):
    test = fresh(test)
    return services.review_test(
        actor=people[who],
        pin=PIN,
        test=test,
        expected_revision=test.revision,
        reason="Raw data checked",
    )


def complete(people, test, *values, batch=None, reviewer="reviewer"):
    """Batch (when given), record, submit and review a test with conforming QC."""
    if batch is not None:
        services.assign_to_batch(actor=people["analyst"], test=test, batch=batch, reason="Run")
    record(people, test, *values)
    submit(people, test)
    return review(people, test, who=reviewer)
