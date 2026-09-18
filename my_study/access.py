from functools import wraps

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied


ALLOWED_STUDY_STATUSES = {"SCHOLAR", "ALTERNATIVE"}


def get_study_status(user):
    try:
        return user.user_info.status
    except (AttributeError, ObjectDoesNotExist):
        return None


def study_access_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if get_study_status(request.user) not in ALLOWED_STUDY_STATUSES:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


def available_courses_for(user, queryset):
    if get_study_status(user) == "ALTERNATIVE":
        return queryset.filter(available_to_alternative=True)
    return queryset
