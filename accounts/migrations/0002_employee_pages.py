# Employees are managed on the site's own Employees pages, not Django admin, so the
# add/change/delete/view_employee permissions 0001 gave the Super Admin group are dropped.

from django.db import migrations


def drop_employee_admin_permissions(apps, schema_editor):
    apps.get_model('auth', 'Permission').objects.filter(
        content_type__app_label='accounts', content_type__model='employee').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='employee',
            options={'default_permissions': (), 'verbose_name': 'employee', 'verbose_name_plural': 'employees'},
        ),
        migrations.RunPython(drop_employee_admin_permissions, migrations.RunPython.noop),
    ]
