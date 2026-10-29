from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from admin.context_processors import role

from .decorators import edit_required, view_required
from .models import MANAGER, MONITOR, SUPER_ADMIN


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

    def test_migrations_create_the_three_roles(self):
        perms = {g.name: set(g.permissions.values_list('codename', flat=True)) for g in Group.objects.all()}
        self.assertEqual(perms, {
            SUPER_ADMIN: {'view_site', 'edit_site', 'manage_employees'},
            MANAGER: {'view_site', 'edit_site'},
            MONITOR: {'view_site'},
        })

    def test_anonymous_goes_to_login(self):
        response = page(self.request(AnonymousUser()))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_access_by_role(self):
        # (employee, can view, can edit, can open the Employees pages)
        cases = [
            (self.user('nobody'), False, False, False),
            (self.user('monitor', MONITOR), True, False, False),
            (self.user('manager', MANAGER), True, True, False),
            (self.user('super', SUPER_ADMIN), True, True, True),
            (self.user('root', is_superuser=True), True, True, True),
        ]
        for user, view, edit, manage in cases:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                got = (self.allowed(page, user), self.allowed(action, user),
                       self.client.get('/employees/').status_code == 200)
                self.assertEqual(got, (view, edit, manage))

    def test_role_labels(self):
        cases = [(self.user('a', SUPER_ADMIN), SUPER_ADMIN), (self.user('b', is_superuser=True), SUPER_ADMIN),
                 (self.user('c', MANAGER), MANAGER), (self.user('d', MONITOR), MONITOR), (self.user('e'), 'No role')]
        for user, label in cases:
            self.assertEqual(role(self.request(user))['role'], label)


class EmployeePagesTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user('boss', password='x')
        self.boss.groups.add(Group.objects.get(name=SUPER_ADMIN))
        self.client.force_login(self.boss)

    def test_pages_render(self):
        for url in ['/employees/', '/employees/new/', f'/employees/{self.boss.pk}/',
                    f'/employees/{self.boss.pk}/password/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_requires_a_role_and_gives_exactly_one(self):
        form = {'username': 'newbie', 'password1': 'S3cure-pass!', 'password2': 'S3cure-pass!'}
        response = self.client.post('/employees/new/', form)
        self.assertContains(response, 'This field is required')
        self.assertFalse(User.objects.filter(username='newbie').exists())

        self.client.post('/employees/new/', {**form, 'role': MANAGER})
        newbie = User.objects.get(username='newbie')
        self.assertEqual(list(newbie.groups.values_list('name', flat=True)), [MANAGER])
        self.assertTrue(newbie.check_password('S3cure-pass!'))

    def test_edit_replaces_the_role(self):
        clerk = User.objects.create_user('clerk')
        clerk.groups.add(Group.objects.get(name=MONITOR))
        self.client.post(f'/employees/{clerk.pk}/', {'username': 'clerk', 'role': MANAGER, 'is_active': 'on'})
        self.assertEqual(list(clerk.groups.values_list('name', flat=True)), [MANAGER])

    def test_edit_page_shows_current_role(self):
        root = User.objects.create_superuser('root', password='x')  # createsuperuser account: no group yet
        html = self.client.get(f'/employees/{root.pk}/').content.decode()
        self.assertRegex(html, r'<input type="radio" name="role" value="Super Admin"[^>]*checked')

    def test_cannot_remove_own_super_admin_access(self):
        for data in [{'role': MANAGER, 'is_active': 'on'}, {'role': SUPER_ADMIN}]:
            with self.subTest(data=data):
                response = self.client.post(f'/employees/{self.boss.pk}/', {'username': 'boss', **data})
                self.assertContains(response, "can&#x27;t remove your own Super Admin access")
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.is_active)
        self.assertEqual(list(self.boss.groups.values_list('name', flat=True)), [SUPER_ADMIN])

    def test_set_password_keeps_own_session(self):
        self.client.post(f'/employees/{self.boss.pk}/password/',
                         {'new_password1': 'N3w-secret-pw', 'new_password2': 'N3w-secret-pw'})
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.check_password('N3w-secret-pw'))
        self.assertEqual(self.client.get('/employees/').status_code, 200)
