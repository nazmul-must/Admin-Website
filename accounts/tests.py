"""Tests for employee roles, the employee pages, sign-in, throttling and the access log."""

import re
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.management import CommandError, call_command
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from admin.context_processors import role

from . import throttle
from .decorators import edit_required, view_required
from .forms import EmployeeCreateForm
from .models import MANAGER, MONITOR, SUPER_ADMIN, AccessLog, email_verified


@view_required
def page(_request):
    return HttpResponse("ok")


@edit_required
def action(_request):
    return HttpResponse("ok")


class RoleTests(TestCase):
    def user(self, name, group=None, **flags):
        u = User.objects.create_user(name, password="x", **flags)
        if group:
            u.groups.add(Group.objects.get(name=group))
        return User.objects.get(pk=u.pk)  # fresh instance: no stale permission cache

    def request(self, user):
        request = RequestFactory().get("/")
        request.user = user
        return request

    def allowed(self, view, user):
        try:
            return view(self.request(user)).status_code == 200
        except PermissionDenied:
            return False

    def test_migrations_create_the_three_roles(self):
        perms = {
            g.name: set(g.permissions.values_list("codename", flat=True))
            for g in Group.objects.all()
        }
        self.assertEqual(
            perms,
            {
                SUPER_ADMIN: {"view_site", "edit_site", "manage_employees"},
                MANAGER: {"view_site", "edit_site"},
                MONITOR: {"view_site"},
            },
        )

    def test_anonymous_goes_to_login(self):
        response = page(self.request(AnonymousUser()))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_access_by_role(self):
        # (employee, can view, can edit, can open the Employees pages)
        cases = [
            (self.user("nobody"), False, False, False),
            (self.user("monitor", MONITOR), True, False, False),
            (self.user("manager", MANAGER), True, True, False),
            (self.user("super", SUPER_ADMIN), True, True, True),
            (self.user("root", is_superuser=True), True, True, True),
        ]
        for user, view, edit, manage in cases:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                got = (
                    self.allowed(page, user),
                    self.allowed(action, user),
                    self.client.get("/employees/").status_code == 200,
                )
                self.assertEqual(got, (view, edit, manage))

    def test_role_labels(self):
        cases = [
            (self.user("a", SUPER_ADMIN), SUPER_ADMIN),
            (self.user("b", is_superuser=True), SUPER_ADMIN),
            (self.user("c", MANAGER), MANAGER),
            (self.user("d", MONITOR), MONITOR),
            (self.user("e"), "No role"),
        ]
        for user, label in cases:
            self.assertEqual(role(self.request(user))["role"], label)


class EmployeePagesTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            "boss@yopmail.com", email="boss@yopmail.com", password="x"
        )
        self.boss.groups.add(Group.objects.get(name=SUPER_ADMIN))
        self.client.force_login(self.boss)

    def invite(self, email="New.Hire@Yopmail.com", role=MANAGER, **extra):
        return self.client.post("/employees/new/", {"email": email, "role": role, **extra})

    def emailed_link(self):
        match = re.search(r"http://testserver(/employees/verify/\S+)", str(mail.outbox[-1].body))
        assert match is not None, "no sign-in link in the email"
        return match.group(1)

    def test_pages_render(self):
        for url in ["/employees/", "/employees/new/", f"/employees/{self.boss.pk}/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_requires_email_and_role(self):
        for missing in ("email", "role"):
            with self.subTest(missing=missing):
                response = self.client.post(
                    "/employees/new/", {"email": "a@yopmail.com", "role": MONITOR, missing: ""}
                )
                self.assertContains(response, "This field is required")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(mail.outbox, [])

    def test_invite_verify_then_sign_in(self):
        self.invite()
        hire = User.objects.get(
            email="new.hire@yopmail.com"
        )  # stored lowercased, also the username
        self.assertEqual(
            (hire.username, list(hire.groups.values_list("name", flat=True))),
            (hire.email, [MANAGER]),
        )
        self.assertFalse(email_verified(hire))
        self.assertEqual(mail.outbox[0].to, ["new.hire@yopmail.com"])
        self.assertIn("Verify your email", str(mail.outbox[0].subject))

        self.client.logout()
        login = {"username": "new.hire@yopmail.com", "password": "S3cure-pass!"}
        self.assertEqual(self.client.post("/login/", login).status_code, 200)  # unverified: refused

        link = self.emailed_link()
        form_url = self.client.get(link)["Location"]  # Django swaps the token out of the URL
        response = self.client.post(
            form_url, {"new_password1": "S3cure-pass!", "new_password2": "S3cure-pass!"}
        )
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        hire.refresh_from_db()
        self.assertTrue(email_verified(hire))

        self.assertRedirects(
            self.client.post("/login/", {**login, "username": " NEW.hire@yopmail.com "}),
            "/",
            fetch_redirect_response=False,
        )
        self.client.logout()
        self.assertContains(self.client.get(link, follow=True), "Link Expired")  # single use

    def test_email_is_unique_ignoring_case(self):
        self.invite("Boss@Yopmail.com")
        self.assertEqual(User.objects.count(), 1)
        self.assertContains(
            self.invite("Boss@Yopmail.com"), "Another employee already uses this email."
        )

    def test_changing_someone_elses_email_needs_verification_again(self):
        clerk = User.objects.create_user(
            "clerk@yopmail.com", email="clerk@yopmail.com", password="x"
        )
        clerk.groups.add(Group.objects.get(name=MONITOR))
        self.client.post(
            f"/employees/{clerk.pk}/",
            {"email": "clerk2@yopmail.com", "role": MANAGER, "is_active": "on"},
        )
        clerk.refresh_from_db()
        self.assertEqual(
            (clerk.username, clerk.email), ("clerk2@yopmail.com", "clerk2@yopmail.com")
        )
        self.assertEqual(list(clerk.groups.values_list("name", flat=True)), [MANAGER])
        self.assertFalse(email_verified(clerk))
        self.assertEqual(mail.outbox[-1].to, ["clerk2@yopmail.com"])

    def test_role_change_alone_keeps_verification(self):
        clerk = User.objects.create_user(
            "clerk@yopmail.com", email="clerk@yopmail.com", password="x"
        )
        self.client.post(
            f"/employees/{clerk.pk}/",
            {"email": "clerk@yopmail.com", "role": MONITOR, "is_active": "on"},
        )
        clerk.refresh_from_db()
        self.assertTrue(email_verified(clerk))
        self.assertEqual(mail.outbox, [])

    def test_resend_link(self):
        self.invite()
        hire = User.objects.get(email="new.hire@yopmail.com")
        self.client.post(f"/employees/{hire.pk}/send-link/")
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            self.client.get(f"/employees/{hire.pk}/send-link/").status_code, 405
        )  # POST only

    def test_edit_page_shows_current_role(self):
        root = User.objects.create_superuser(
            "root", password="x"
        )  # createsuperuser account: no group yet
        html = self.client.get(f"/employees/{root.pk}/").content.decode()
        self.assertRegex(html, r'<input type="radio" name="role" value="Super Admin"[^>]*checked')

    def test_cannot_remove_own_access_or_change_own_email(self):
        for data in [{"role": MANAGER, "is_active": "on"}, {"role": SUPER_ADMIN}]:
            with self.subTest(data=data):
                response = self.client.post(
                    f"/employees/{self.boss.pk}/", {"email": "boss@yopmail.com", **data}
                )
                self.assertContains(response, "can&#x27;t remove your own Super Admin access")
        self.client.post(
            f"/employees/{self.boss.pk}/",
            {"email": "other@yopmail.com", "role": SUPER_ADMIN, "is_active": "on"},
        )
        self.boss.refresh_from_db()
        self.assertEqual((self.boss.email, self.boss.is_active), ("boss@yopmail.com", True))
        self.assertTrue(email_verified(self.boss))
        self.assertEqual(list(self.boss.groups.values_list("name", flat=True)), [SUPER_ADMIN])


class CreateSuperAdminCommandTests(TestCase):
    def run_command(self, *passwords, email=" First@Yopmail.com "):
        with patch("getpass.getpass", side_effect=passwords):
            call_command("create_super_admin", email=email, stdout=StringIO(), stderr=StringIO())

    def test_creates_verified_super_admin_without_email(self):
        # mismatch, then too common, then accepted
        self.run_command(
            "Aa-111111", "Bb-222222", "password", "password", "S3cure-pass!", "S3cure-pass!"
        )
        first = User.objects.get(email="first@yopmail.com")
        self.assertEqual(first.username, "first@yopmail.com")
        self.assertEqual(list(first.groups.values_list("name", flat=True)), [SUPER_ADMIN])
        self.assertTrue(email_verified(first) and first.check_password("S3cure-pass!"))
        self.assertEqual(mail.outbox, [])
        self.assertTrue(self.client.login(username="first@yopmail.com", password="S3cure-pass!"))

    def test_refuses_existing_email(self):
        self.run_command("S3cure-pass!", "S3cure-pass!")
        with self.assertRaisesMessage(CommandError, "already an employee"):
            self.run_command(email="FIRST@yopmail.com")

    def test_finishes_an_invited_employee_who_never_verified(self):
        invited = User.objects.create_user(
            "first@yopmail.com", email="first@yopmail.com"
        )  # unusable password
        self.run_command("S3cure-pass!", "S3cure-pass!")
        invited.refresh_from_db()
        self.assertTrue(invited.check_password("S3cure-pass!"))
        self.assertEqual(User.objects.count(), 1)


class SignInThrottleTests(TestCase):
    """Repeated failed sign-ins lock the email; success clears the count."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.employee = User.objects.create_user(
            "ops@yopmail.com", email="ops@yopmail.com", password="S3cure-pass!"
        )

    def sign_in(self, password):
        return self.client.post("/login/", {"username": "ops@yopmail.com", "password": password})

    def test_locks_after_max_failures_even_with_the_right_password(self):
        for _ in range(throttle.MAX_FAILURES):
            self.assertContains(self.sign_in("wrong"), "Please enter a correct email and password")
        self.assertContains(self.sign_in("S3cure-pass!"), "Too many failed sign-ins")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_success_clears_earlier_failures(self):
        for _ in range(throttle.MAX_FAILURES - 1):
            self.sign_in("wrong")
        self.assertEqual(self.sign_in("S3cure-pass!").status_code, 302)
        self.client.logout()
        self.sign_in("wrong")
        self.assertFalse(throttle.is_locked("ops@yopmail.com"))


class AccessLogTests(TestCase):
    """Every request by a signed-in employee is recorded; anonymous ones and probes are not."""

    def test_records_signed_in_requests_with_query_string(self):
        boss = User.objects.create_user("boss@yopmail.com", email="boss@yopmail.com", password="x")
        boss.groups.add(Group.objects.get(name=SUPER_ADMIN))
        self.client.get("/employees/")  # anonymous: redirected to login, not recorded
        self.client.force_login(boss)
        self.client.get("/employees/?q=ada%40yopmail.com")
        self.client.get("/health/")
        rows = list(AccessLog.objects.values_list("email", "method", "path", "status"))
        self.assertEqual(
            rows, [("boss@yopmail.com", "GET", "/employees/?q=ada%40yopmail.com", 200)]
        )

    def test_keeps_the_email_when_the_employee_is_deleted(self):
        clerk = User.objects.create_user(
            "clerk@yopmail.com", email="clerk@yopmail.com", password="x"
        )
        self.client.force_login(clerk)
        self.client.get("/")
        clerk.delete()
        log = AccessLog.objects.get()
        self.assertEqual((log.employee, log.email, log.status), (None, "clerk@yopmail.com", 403))


class EmployeeFormCommitTests(TestCase):
    """`save(commit=False)` saves nothing until the caller saves, as ModelForm promises."""

    def test_commit_false_defers_row_and_role(self):
        form = EmployeeCreateForm({"email": "later@yopmail.com", "role": MONITOR})
        self.assertTrue(form.is_valid())
        employee = form.save(commit=False)
        self.assertFalse(User.objects.filter(email="later@yopmail.com").exists())
        employee.save()
        form.save_m2m()
        self.assertEqual(list(employee.groups.values_list("name", flat=True)), [MONITOR])
        self.assertFalse(email_verified(employee))
