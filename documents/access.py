from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db.models import Q


def is_alternative_user(user):
    try:
        return user.user_info.status == "ALTERNATIVE"
    except (AttributeError, ObjectDoesNotExist):
        return False


def available_document_types_for(user, queryset):
    if is_alternative_user(user):
        return queryset.filter(available_to_alternative=True)
    return queryset


def available_documents_for(user, queryset):
    if is_alternative_user(user):
        return queryset.filter(
            Q(document_type__isnull=True)
            | Q(document_type__available_to_alternative=True)
        )
    return queryset


def ensure_document_type_available(user, document_type):
    if is_alternative_user(user) and not document_type.available_to_alternative:
        raise PermissionDenied


def ensure_document_available(user, document):
    if document.document_type_id:
        ensure_document_type_available(user, document.document_type)
