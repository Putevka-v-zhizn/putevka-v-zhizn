from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.contrib.auth import get_user_model
from django.db import transaction

from core.models import UserProgramPreferences


def legacy_program_defaults(user):
    """Compatibility for accounts created outside the public registration flow."""
    from nto_travel.models import NtoApplication
    nto = NtoApplication.objects.filter(user=user).exists()
    try:
        info = user.user_info
        main = not nto or info.form_status != "draft" or info.status != "CANDIDATE"
    except ObjectDoesNotExist:
        main = not nto
    return dict(main_enabled=main, nto_enabled=nto, active_program="nto" if nto else "main")


def get_program_preferences(user):
    if hasattr(user, "_resolved_program_preferences"):
        return user._resolved_program_preferences
    try:
        preferences = user.program_preferences
    except ObjectDoesNotExist:
        preferences = UserProgramPreferences(user=user, **legacy_program_defaults(user))
    user._resolved_program_preferences = preferences
    return preferences


@transaction.atomic
def select_program(user, program):
    if program not in UserProgramPreferences.Program.values:
        raise ValidationError("Выберите одну из доступных программ.")
    # Lock the account as well: it serializes concurrent first-time selections.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    preferences, _ = UserProgramPreferences.objects.get_or_create(
        user=user, defaults=legacy_program_defaults(user),
    )
    setattr(preferences, f"{program}_enabled", True)
    preferences.active_program = program
    preferences.save(update_fields=[f"{program}_enabled", "active_program"])
    return preferences


def request_program(request, preferences):
    match = request.resolver_match
    if match and match.app_name == "nto_travel" and preferences.nto_enabled:
        return "nto"
    if is_main_program_path(request.path) and preferences.main_enabled:
        return "main"
    return preferences.active_program


def is_main_program_path(path):
    return (
        path.startswith(("/documents/", "/family-income/", "/study/", "/motivation/"))
        or (path.startswith("/form/") and not path.startswith("/form/personal-info/"))
    )
