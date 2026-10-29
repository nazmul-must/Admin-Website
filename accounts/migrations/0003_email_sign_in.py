# Employees sign in with their email, stored lowercased in `username` (accounts/forms.py).
# Existing employees that already have an email switch to it now; those without one keep
# their username until a Super Admin adds an email on the Employees page.

from django.db import migrations


def use_email_as_username(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    for user in User.objects.exclude(email=''):
        email = user.email.strip().lower()
        if User.objects.filter(username__iexact=email).exclude(pk=user.pk).exists():
            continue  # another account already signs in with this address; leave both alone
        user.email = user.username = email
        user.save(update_fields=['email', 'username'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_employee_pages'),
    ]

    operations = [
        migrations.RunPython(use_email_as_username, migrations.RunPython.noop),
    ]
