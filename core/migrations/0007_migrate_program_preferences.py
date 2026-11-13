from django.db import migrations
from django.db.models import Q


def migrate_preferences(apps, schema_editor):
    alias = schema_editor.connection.alias
    User = apps.get_model('auth', 'User')
    Preferences = apps.get_model('core', 'UserProgramPreferences')
    Registration = apps.get_model('core', 'RegistrationPersonalData')
    Application = apps.get_model('nto_travel', 'NtoApplication')
    UserInfo = apps.get_model('scholar_form', 'UserInfo')
    nto_users = set(Registration.objects.using(alias).exclude(nto_campaign_slug='').values_list('user_id', flat=True))
    nto_users.update(Application.objects.using(alias).values_list('user_id', flat=True))
    main_users = set(UserInfo.objects.using(alias).filter(
        ~Q(form_status='draft') | ~Q(status='CANDIDATE')
    ).values_list('user_id', flat=True))
    pending = []
    for user_id in User.objects.using(alias).filter(is_staff=False, is_superuser=False).values_list('pk', flat=True).iterator(chunk_size=500):
        nto = user_id in nto_users
        pending.append(Preferences(user_id=user_id, nto_enabled=nto,
                                   main_enabled=not nto or user_id in main_users,
                                   active_program='nto' if nto else 'main'))
        if len(pending) >= 500:
            Preferences.objects.using(alias).bulk_create(pending, ignore_conflicts=True)
            pending = []
    Preferences.objects.using(alias).bulk_create(pending, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0006_userprogrampreferences_and_more'),
        ('nto_travel', '0002_ntoapplication_nto_campaign_status_idx'),
        ('scholar_form', '0006_userpersonaldata_accepted_at'),
    ]
    operations = [migrations.RunPython(migrate_preferences, migrations.RunPython.noop)]
