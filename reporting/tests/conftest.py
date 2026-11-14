from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from core.models import RuleSet
from core.services import set_pin
from quality.services import add_sample, dispose_lot, receive_lot, record_result, review_result
from reporting import evidence
from tests.receipts import on_site_receipt

PIN = "73519482"
PASSWORD = "synthetic-test-password-2026"


@pytest.fixture(autouse=True)
def _foundation_journey(settings):
    """The foundation numeric-entry journey is development-only (quality.services)."""
    settings.DEBUG = True


@pytest.fixture(autouse=True)
def _collectors_isolated():
    """Start each test with no sibling collectors (the platform registers some at startup)
    and restore them afterwards so other suites in the same session still see them."""
    saved = dict(evidence._collectors)
    evidence._collectors.clear()
    yield
    evidence._collectors.clear()
    evidence._collectors.update(saved)


def make_user(django_user_model, name, *roles):
    user = django_user_model.objects.create_user(
        name, password=PASSWORD, first_name=name.title(), last_name="Synthetic"
    )
    for role in roles:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
    set_pin(actor=user, pin=PIN, password=PASSWORD)
    return user


@pytest.fixture
def people(django_user_model):
    return {
        "analyst": make_user(django_user_model, "analyst", "analyst"),
        "reviewer": make_user(django_user_model, "reviewer", "reviewer"),
        "quality": make_user(django_user_model, "quality", "quality"),
        "quality2": make_user(django_user_model, "quality2", "quality"),
        "auditor": make_user(django_user_model, "auditor", "auditor"),
        "nobody": make_user(django_user_model, "nobody"),
    }


def build_lot(people, number="SYN-100", release=True, unit="mg/g", value="99.5", extra_tests=()):
    """A synthetic lot taken through reviewed results and signed QC disposition."""
    rules = RuleSet.objects.create(
        code=f"synthetic-{number}",
        segment="chemical",
        author=people["quality"],
        status="approved",
        effective_from=timezone.now() - timedelta(hours=1),
        effective_until=timezone.now() + timedelta(days=365),
        policy={
            "required_tests": ["assay", *extra_tests],
            "review_meaning": "reviewed",
            "disposition_meaning": "approved",
        },
    )
    lot = receive_lot(
        actor=people["analyst"],
        number=number,
        material="Synthetic reference powder",
        rules=rules,
        reason="Synthetic receipt",
        receipt=on_site_receipt(),
    )
    sample = add_sample(
        actor=people["analyst"],
        lot=lot,
        reference=f"{number}-S1",
        collected_at=timezone.now() - timedelta(minutes=30),
        reason="Synthetic sampling",
    )
    results = []
    for test in ["assay", *extra_tests]:
        result = record_result(
            actor=people["analyst"],
            sample=sample,
            reason="Synthetic measurement",
            test_code=test,
            value=Decimal(value),
            unit=unit,
            lower_limit=Decimal("98.0"),
            upper_limit=Decimal("101.0"),
        )
        results.append(result)
    if release:
        for result in results:
            review_result(
                actor=people["reviewer"],
                pin=PIN,
                result=result,
                expected_revision=1,
                reason="Source data checked",
            )
        lot.refresh_from_db()
        dispose_lot(
            actor=people["quality"],
            pin=PIN,
            lot=lot,
            expected_revision=lot.revision,
            reason="Complete and conforming",
        )
        lot.refresh_from_db()
    return lot


@pytest.fixture
def lot(people):
    return build_lot(people)
