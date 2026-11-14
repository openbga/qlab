"""The shared menu offers only destinations the signed-in account can read."""

from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.urls import reverse

from accounts.context_processors import account_navigation

pytestmark = pytest.mark.django_db

WORKSPACE_PATHS = {
    "/",
    "/sampling/",
    "/testing/",
    "/stability/",
    "/laboratory/",
    "/catalog/",
    "/suppliers/",
    "/rules/",
    "/reports/",
}
ACCOUNT_PATHS = {"/signature-pin/", "/accounts/access/"}
ADMIN_PATHS = {"/accounts/users/", "/accounts/announcement/"}


class PrimaryNavigation(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.inside = False
        self.links = set()
        self.headings = set()
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and attrs.get("aria-label") == "Primary":
            self.inside = True
        if self.inside and tag == "a":
            self.links.add(attrs["href"])
        if self.inside and tag == "p" and attrs.get("class") == "vr-nav-heading":
            self.headings.add(attrs["id"])

    def handle_endtag(self, tag):
        if tag == "nav":
            self.inside = False


@pytest.mark.parametrize(
    "roles,staff,superuser",
    [
        (["analyst"], False, False),
        (["reviewer"], False, False),
        (["quality"], False, False),
        (["auditor"], False, False),
        (["admin"], False, False),
        (["analyst", "reviewer"], False, False),
        (["analyst", "auditor"], False, False),
        (["reviewer", "admin"], False, False),
        ([], False, False),
        (["unrelated"], False, False),
        ([], True, False),
        ([], True, True),
        (["analyst"], True, True),
    ],
)
def test_menu_matches_destination_access(client, django_user_model, roles, staff, superuser):
    user = django_user_model.objects.create_user(
        username="navigation-test", is_staff=staff, is_superuser=superuser
    )
    user.groups.set([Group.objects.get_or_create(name=role)[0] for role in roles])
    client.force_login(user)
    response = client.get(reverse("accounts:access"))
    assert response.status_code == 200
    nav = PrimaryNavigation(response)
    expected = set(ACCOUNT_PATHS)
    headings = {"vr-nav-account"}
    if set(roles) & {"analyst", "reviewer", "quality", "auditor", "admin"}:
        expected |= WORKSPACE_PATHS
        headings |= {"vr-nav-work", "vr-nav-configuration", "vr-nav-records"}
    if set(roles) & {"admin", "quality", "auditor"}:
        expected.add("/audit/")
    if "admin" in roles:
        expected |= ADMIN_PATHS
    assert nav.links == expected
    assert nav.headings == headings

    # Compare the rendered menu to the actual route guards, including denied deep links.
    destinations = WORKSPACE_PATHS | ACCOUNT_PATHS | ADMIN_PATHS | {"/audit/"}
    for path in destinations:
        destination = client.get(path)
        if path in expected:
            assert destination.status_code == 200, path
        elif path == "/":
            assert destination.status_code == 302
            assert destination.url == reverse("accounts:access")
        else:
            assert destination.status_code == 403, path


def test_navigation_refreshes_after_role_changes(client, django_user_model):
    user = django_user_model.objects.create_user(username="changing-roles")
    analyst = Group.objects.get_or_create(name="analyst")[0]
    auditor = Group.objects.get_or_create(name="auditor")[0]
    user.groups.add(analyst)
    client.force_login(user)
    url = reverse("accounts:access")
    assert "/audit/" not in PrimaryNavigation(client.get(url)).links
    user.groups.add(auditor)
    assert "/audit/" in PrimaryNavigation(client.get(url)).links
    user.groups.clear()
    assert PrimaryNavigation(client.get(url)).links == ACCOUNT_PATHS


def test_anonymous_and_inactive_accounts_have_no_role_navigation(django_user_model):
    inactive = django_user_model.objects.create_user(username="inactive", is_active=False)
    inactive.groups.add(Group.objects.get_or_create(name="admin")[0])
    for user in (AnonymousUser(), inactive):
        context = account_navigation(SimpleNamespace(user=user))
        assert context["can_view_workspace"] is False
        assert context["can_view_audit"] is False
        assert context["can_manage_accounts"] is False
