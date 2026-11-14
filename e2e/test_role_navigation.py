"""Role-filtered navigation after real sign-in, on desktop and phone screens."""

import re
import secrets

import pytest
from django.contrib.auth.models import Group
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "roles",
    [
        ("analyst",),
        ("reviewer",),
        ("quality",),
        ("auditor",),
        ("admin",),
        ("analyst", "auditor"),
        (),
    ],
)
def test_menu_after_sign_in(live_server, django_user_model, artifacts, roles):
    password = secrets.token_urlsafe(24)
    user = django_user_model.objects.create_user(username="navigation-test", password=password)
    user.groups.set([Group.objects.get_or_create(name=role)[0] for role in roles])
    expected = ["Signature PIN", "Account access"]
    if roles:
        expected = [
            "Lots",
            "Sampling",
            "Testing",
            "Stability",
            "Laboratory",
            "Specifications",
            "Suppliers",
            "Rule sets",
            "Certificates",
            *(["Audit trail"] if set(roles) & {"admin", "quality", "auditor"} else []),
            *expected,
        ]
    if "admin" in roles:
        expected += ["Users and roles", "Sign-in announcement"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        try:
            page.goto(f"{live_server.url}/accounts/login/")
            page.get_by_label(re.compile(r"^Username\b")).fill(user.username)
            page.get_by_label(re.compile(r"^Password\b")).fill(password)
            page.get_by_role("button", name="Sign in", exact=True).click()
            landing = "/" if roles else "/accounts/access/"
            expect(page).to_have_url(f"{live_server.url}{landing}")
            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 900})
                if width == 390:
                    page.get_by_role("button", name="Menu", exact=True).click()
                # Bootstrap gives the open phone drawer dialog semantics.
                nav = page.get_by_role(
                    "dialog" if width == 390 else "navigation", name="Primary", exact=True
                )
                expect(nav).to_be_visible()
                expect(nav.locator("a")).to_have_text(expected)
                expect(nav.locator(".vr-nav-heading")).to_have_text(
                    ["Work", "Configuration", "Records", "Account"] if roles else ["Account"]
                )
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                if roles in (("analyst",), ("auditor",), ()):
                    name = "-".join(roles) or "unassigned"
                    page.screenshot(path=str(artifacts / f"navigation-{name}-{width}.png"))
                nav.get_by_role("link", name="Account access", exact=True).click()
                expect(page).to_have_url(f"{live_server.url}/accounts/access/")
                expect(page.locator('#vr-nav [aria-current="page"]')).to_have_text("Account access")

            # Read the in-app guidance beside the actual menu, including for a roleless account.
            page.set_viewport_size({"width": 1440, "height": 900})
            page.get_by_role("button", name="Page documentation", exact=True).click()
            panel = page.get_by_role("complementary", name="Page documentation", exact=True)
            expect(panel).to_be_visible()
            expect(panel).to_contain_text("The shared menu shows destinations your assigned roles")
            expect(panel).to_contain_text("Menu access combines all your assigned roles")
        except Exception:
            page.screenshot(path=str(artifacts / "role-navigation-failure.png"), full_page=True)
            raise
        finally:
            browser.close()
