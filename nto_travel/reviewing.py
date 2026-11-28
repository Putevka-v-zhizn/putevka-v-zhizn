from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import NtoApplication, NtoApplicationReview, NtoApplicationRead, NtoApplicationEvent


REVIEW_FIELDS = {
    "criticality": "Критичность поддержки", "criticality_reason": "Обоснование критичности",
    "motivation": "Мотивация", "motivation_reason": "Обоснование мотивации",
}


class ReviewConflict(Exception):
    pass


def require_reviewer(user):
    if not user.is_staff or not all(user.has_perm("nto_travel." + code) for code in ("view_nto_application", "review_nto_application")):
        raise PermissionDenied


def _mark_read(app, user):
    mark, created = NtoApplicationRead.objects.get_or_create(application=app, user=user)
    if created:
        NtoApplicationEvent.objects.create(application=app, actor=user, action="marked_read", old_status=app.status, new_status=app.status)
    return mark


@transaction.atomic
def mark_read(application_id, user):
    require_reviewer(user)
    app = NtoApplication.objects.select_for_update().get(pk=application_id)
    return _mark_read(app, user)


@transaction.atomic
def save_review(application_id, user, data):
    require_reviewer(user)
    app = NtoApplication.objects.select_for_update().get(pk=application_id)
    if app.status == NtoApplication.Status.DRAFT:
        raise ValidationError("Заключение доступно после отправки заявки участником.")
    current = NtoApplicationReview.objects.filter(application=app).first()
    if data["version"] != (current.version if current else 0):
        raise ReviewConflict("Коллега уже изменил заключение. Обновите страницу и сравните ответы перед сохранением.")
    changed = [key for key in REVIEW_FIELDS if not current or getattr(current, key) != data[key]]
    if changed:
        comment = "\n\n".join(
            f"{REVIEW_FIELDS[key]}\nБыло: {getattr(current, key) if current else 'Не указано'}\nСтало: {data[key]}"
            for key in changed
        )
        review = current or NtoApplicationReview(application=app)
        for key in REVIEW_FIELDS:
            setattr(review, key, data[key])
        review.author = user
        review.version = current.version + 1 if current else 1
        review.full_clean()
        review.save()
        NtoApplicationEvent.objects.create(application=app, actor=user, action="review_saved", old_status=app.status, new_status=app.status, comment=comment)
    _mark_read(app, user)
    return current if not changed else review
