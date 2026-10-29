from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from admin.context_processors import role

from .decorators import edit_required, view_required
from .models import MANAGER, MONITOR, SUPER_ADMIN, Employee


@view_required
def page(request):
    return HttpResponse('ok')


@edit_required
def action(request):
    return HttpResponse('ok')


class RoleTests(TestCase):
    def user(self, name, group=None, **flags):
        u = User.objects.create_user(name, password='x', **flags)
        if group:
            u.groups.add(Group.objects.get(name=group))
        return User.objects.get(pk=u.pk)  # fresh instance: no stale permission cache

    def request(self, user):
        request = RequestFactory().get('/')
        request.user = user
        return request

    def allowed(self, view, user):
        try:
            return view(self.request(user)).status_code == 200
        except PermissionDenied:
            return False

    def test_migration_creates_the_three_groups(self):
        self.assertEqual(set(Group.objects.values_list('name', flat=True)), {SUPER_ADMIN, MANAGER, MONITOR})

    def test_anonymous_goes_to_login(self):
        response = page(self.request(AnonymousUser()))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_access_by_role(self):
        # (employee, can view, can edit, can manage employees at /admin/)
        cases = [
            (self.user('nobody'), False, False, False),
            (self.user('monitor', MONITOR), True, False, False),
            (self.user('manager', MANAGER), True, True, False),
            (self.user('super', SUPER_ADMIN), True, True, True),
            (self.user('root', is_superuser=True), True, True, True),
        ]
        for user, view, edit, manage in cases:
            with self.subTest(user=user.username):
                got = (self.allowed(page, user), self.allowed(action, user),
                       admin.site.has_permission(self.request(user)), user.has_perm('accounts.change_employee'))
                self.assertEqual(got, (view, edit, manage, manage))

    def test_role_labels(self):
        cases = [(self.user('a', SUPER_ADMIN), SUPER_ADMIN), (self.user('b', is_superuser=True), SUPER_ADMIN),
                 (self.user('c', MANAGER), MANAGER), (self.user('d', MONITOR), MONITOR), (self.user('e'), 'No role')]
        for user, label in cases:
            self.assertEqual(role(self.request(user))['role'], label)

    def test_admin_lists_employees_not_users_or_groups(self):
        registered = set(admin.site._registry)
        self.assertIn(Employee, registered)
        self.assertFalse({User, Group} & registered)

    def test_super_admin_group_can_open_employee_pages(self):
        boss = self.user('boss', SUPER_ADMIN)
        monitor = self.user('watcher', MONITOR)
        self.client.force_login(boss)
        for url in ['/admin/accounts/employee/', '/admin/accounts/employee/add/',
                    f'/admin/accounts/employee/{monitor.pk}/change/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(monitor)
        self.assertEqual(self.client.get('/admin/accounts/employee/').status_code, 302)  # to login

    def test_role_is_required_and_single(self):
        self.client.force_login(self.user('boss', SUPER_ADMIN))
        form = {'username': 'newbie', 'usable_password': 'true', 'password1': 'S3cure-pass!', 'password2': 'S3cure-pass!'}
        response = self.client.post('/admin/accounts/employee/add/', form)
        self.assertContains(response, 'This field is required')
        self.assertFalse(User.objects.filter(username='newbie').exists())

        self.client.post('/admin/accounts/employee/add/', {**form, 'role': MANAGER})
        newbie = User.objects.get(username='newbie')
        self.assertEqual(list(newbie.groups.values_list('name', flat=True)), [MANAGER])

    def test_change_page_shows_current_role(self):
        root = self.user('root', is_superuser=True)  # createsuperuser account: no group yet
        self.client.force_login(root)
        html = self.client.get(f'/admin/accounts/employee/{root.pk}/change/').content.decode()
        self.assertRegex(html, r'<input type="radio" name="role" value="Super Admin"[^>]*checked')
