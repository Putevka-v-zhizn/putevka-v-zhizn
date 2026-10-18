from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


def create_nto_groups(sender, apps, using, **kwargs):
    application = apps.get_model("nto_travel", "NtoApplication")
    campaign = apps.get_model("nto_travel", "NtoCampaign")
    profile = apps.get_model("nto_travel", "NtoProfile")
    consent = apps.get_model("nto_travel", "NtoConsentRevision")
    app_content_type = ContentType.objects.db_manager(using).get_for_model(application)
    campaign_content_type = ContentType.objects.db_manager(using).get_for_model(campaign)
    permission_codes = {
        "view_nto_application": app_content_type,
        "review_nto_application": app_content_type,
        "export_nto_application": app_content_type,
        "manage_nto_campaign": campaign_content_type,
    }
    reviewer, _ = Group.objects.db_manager(using).get_or_create(name="Проверяющий НТО")
    administrator, _ = Group.objects.db_manager(using).get_or_create(name="Администратор НТО")
    reviewer.permissions.set([
        Permission.objects.using(using).get(content_type=permission_codes[code], codename=code)
        for code in ("view_nto_application", "review_nto_application")
    ])
    admin_permissions = [
        Permission.objects.using(using).get(content_type=content_type, codename=code)
        for code, content_type in permission_codes.items()
    ]
    for model in (campaign, profile, consent):
        content_type = ContentType.objects.db_manager(using).get_for_model(model)
        for action in ("add", "change", "view"):
            admin_permissions.append(Permission.objects.using(using).get(
                content_type=content_type, codename=f"{action}_{model._meta.model_name}"
            ))
    administrator.permissions.set(admin_permissions)
