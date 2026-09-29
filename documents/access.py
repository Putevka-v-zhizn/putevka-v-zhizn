from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db.models import Q


def is_alternative_user(user):
    try:
        return user.user_info.status == "ALTERNATIVE"
    except (AttributeError, ObjectDoesNotExist):
        return False


def available_document_types_for(user, queryset):
    if is_alternative_user(user):
        return queryset.filter(audience__in=("alternative", "all"))
    return queryset.filter(audience__in=("program", "all"))


def available_documents_for(user, queryset):
    if is_alternative_user(user):
        return queryset.filter(
            Q(document_type__isnull=True)
            | Q(document_type__audience__in=("alternative", "all"))
        )
    return queryset.filter(
        Q(document_type__isnull=True)
        | Q(document_type__audience__in=("program", "all"))
    )


def ensure_document_type_available(user, document_type):
    allowed_audiences = (
        ("alternative", "all") if is_alternative_user(user) else ("program", "all")
    )
    if document_type.audience not in allowed_audiences:
        raise PermissionDenied


def ensure_document_available(user, document):
    if document.document_type_id:
        ensure_document_type_available(user, document.document_type)
