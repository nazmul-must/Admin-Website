# Django's admin app was removed (employees are managed on the site's own pages). Databases
# created before that still hold its log table, whose foreign key to auth_user blocks deleting
# employees. Drop the table and forget the admin app's migrations.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_email_sign_in'),
    ]

    operations = [
        migrations.RunSQL('DROP TABLE IF EXISTS django_admin_log', migrations.RunSQL.noop),
        migrations.RunSQL("DELETE FROM django_migrations WHERE app = 'admin'", migrations.RunSQL.noop),
    ]
