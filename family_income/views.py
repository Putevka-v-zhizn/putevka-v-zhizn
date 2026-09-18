import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from documents.forms import DocumentUploadForm
from documents.models import Document
from scholar_form.models import UserInfo
from scholar_form.services.yandex_disk import (
    YandexDiskError,
    build_document_disk_path,
    delete_resource,
    upload_file_to_yandex_disk,
)

from .forms import FamilyIncomeCaseForm, document_form_for_category
from .models import (
    FamilyIncomeCase, FamilyIncomeDocument, FamilyIncomeInstruction,
    IncomeEvidence, SocialBenefitEvidence,
)
from .notifications import active_staff_users, create_family_income_notification

logger = logging.getLogger(__name__)


def _case_for_user(user):
    user_info, _ = UserInfo.objects.get_or_create(user=user)
    if user_info.status != "FINAL STAGE":
        raise Http404("Раздел доступен только финалистам.")
    case, _ = FamilyIncomeCase.objects.get_or_create(
        user_info=user_info,
        defaults={
            "family_members_count": 1,
            "family_members_description": "",
            "status": FamilyIncomeCase.Status.REVISION,
        },
    )
    # Убираем техническую заглушку, которую могли получить ранние карточки.
    if case.family_members_description == "Не заполнено":
        case.family_members_description = ""
        case.save(update_fields=("family_members_description", "updated_at"))
    return case


def _is_editable(case):
    return case.status == FamilyIncomeCase.Status.REVISION


def _document_title(category, cleaned_data):
    if category == FamilyIncomeDocument.Category.INCOME:
        return f"Доход: {cleaned_data['owner_name']}, {cleaned_data['year']}"
    if category == FamilyIncomeDocument.Category.SOCIAL_BENEFIT:
        return f"Социальная выплата: {cleaned_data['recipient_name']}"
    return cleaned_data["candidate_comment"]


def _document_evidence(item):
    if item.category == FamilyIncomeDocument.Category.INCOME:
        return item.income_evidence
    if item.category == FamilyIncomeDocument.Category.SOCIAL_BENEFIT:
        return item.social_benefit_evidence
    return None


def _has_candidate_response_to_clarification(item):
    if item.review_status != FamilyIncomeDocument.ReviewStatus.CLARIFICATION:
        return False
    if not item.candidate_response_at:
        return False
    return (
        item.clarification_requested_at is None
        or item.candidate_response_at > item.clarification_requested_at
    )


def _sections(case, *, form_with_error=None, error_category=None):
    items_by_category = {category: [] for category, _ in FamilyIncomeDocument.Category.choices}
    documents = case.family_income_documents.select_related("document").prefetch_related("income_evidence", "social_benefit_evidence")
    for item in documents:
        item.has_candidate_response_to_clarification = _has_candidate_response_to_clarification(item)
        items_by_category[item.category].append(item)

    sections = []
    for category, label in FamilyIncomeDocument.Category.choices:
        form = form_with_error if category == error_category else document_form_for_category(category, prefix=category)
        sections.append({"category": category, "label": label, "items": items_by_category[category], "form": form})
    return sections


def _completion(case):
    family_complete = bool(case.family_members_count and case.family_members_description.strip())
    clarification_items = list(case.family_income_documents.filter(
        review_status=FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
    ).only("id", "review_status", "clarification_requested_at", "candidate_response_at"))
    unresolved_clarifications_count = sum(
        not _has_candidate_response_to_clarification(item)
        for item in clarification_items
    )
    return {
        "family_complete": family_complete,
        "documents_added": case.family_income_documents.exists(),
        "clarifications_count": len(clarification_items),
        "unresolved_clarifications_count": unresolved_clarifications_count,
        "can_submit": family_complete,
    }


def _render_page(request, case, *, case_form=None, document_form=None, document_category=None, status=200):
    case_form = case_form or FamilyIncomeCaseForm(instance=case)
    editable = _is_editable(case)
    if not editable:
        for field in case_form.fields.values():
            field.disabled = True
    return render(request, "family_income/page.html", {
        "form": case_form,
        "case": case,
        "editable": editable,
        "sections": _sections(case, form_with_error=document_form, error_category=document_category),
        "completion": _completion(case),
        "instruction": FamilyIncomeInstruction.objects.filter(
            status=FamilyIncomeInstruction.Status.PUBLISHED,
            title__gt="",
            text__gt="",
        ).first(),
        "document_error_category": document_category,
        "active": "family_income",
    }, status=status)


def _validate_upload(file, caption):
    upload_form = DocumentUploadForm({"caption": caption}, {"file": file})
    if upload_form.is_valid():
        return upload_form.cleaned_data["file"], None
    return None, upload_form.errors


def _upload_to_disk(user, uploaded_file):
    disk_path = build_document_disk_path(user, uploaded_file.name, unique_suffix=uuid.uuid4().hex[:8])
    upload_file_to_yandex_disk(
        uploaded_file=uploaded_file,
        disk_path=disk_path,
        log_context={"user_id": user.id, "asset": "family_income"},
    )
    return disk_path


def _save_evidence(item, category, cleaned_data):
    if category == FamilyIncomeDocument.Category.INCOME:
        defaults = {
            name: cleaned_data[name]
            for name in ("year", "owner_name", "gross_amount", "net_amount", "average_monthly_amount")
        }
        IncomeEvidence.objects.update_or_create(family_income_document=item, defaults=defaults)
    elif category == FamilyIncomeDocument.Category.SOCIAL_BENEFIT:
        defaults = {name: cleaned_data[name] for name in ("recipient_name", "benefit_description")}
        SocialBenefitEvidence.objects.update_or_create(family_income_document=item, defaults=defaults)


@login_required
def family_income_page(request):
    case = _case_for_user(request.user)
    if request.method == "POST":
        if not _is_editable(case):
            messages.error(request, "Сведения доступны только для просмотра. Дождитесь запроса на доработку.")
            return redirect("family_income:page")
        form = FamilyIncomeCaseForm(request.POST, instance=case)
        if form.is_valid():
            form.save()
            messages.success(request, "Сведения о семье сохранены.")
            return redirect("family_income:page")
        messages.error(request, "Проверьте заполнение сведений о семье.")
        return _render_page(request, case, case_form=form, status=400)
    return _render_page(request, case)


@login_required
@require_POST
def add_document(request, category):
    case = _case_for_user(request.user)
    if not _is_editable(case):
        messages.error(request, "Добавление документов сейчас недоступно.")
        return redirect("family_income:page")
    try:
        form = document_form_for_category(category, request.POST, request.FILES, prefix=category)
    except ValueError as exc:
        raise Http404("Неизвестная категория документа.") from exc
    if not form.is_valid():
        messages.error(request, "Не удалось сохранить документ. Исправьте указанные ошибки.")
        return _render_page(request, case, document_form=form, document_category=category, status=400)

    title = _document_title(category, form.cleaned_data)
    uploaded_file, upload_errors = _validate_upload(form.cleaned_data["file"], title)
    if upload_errors:
        for errors in upload_errors.values():
            for error in errors:
                messages.error(request, error)
        return _render_page(request, case, document_form=form, document_category=category, status=400)
    try:
        disk_path = _upload_to_disk(request.user, uploaded_file)
    except YandexDiskError:
        logger.exception("Family-income document upload failed for user_id=%s", request.user.id)
        messages.error(request, "Не удалось загрузить файл на Яндекс Диск. Попробуйте ещё раз.")
        return _render_page(request, case, document_form=form, document_category=category, status=502)

    with transaction.atomic():
        document = Document.objects.create(
            user=request.user,
            caption=title,
            user_file_name=uploaded_file.name,
            yandex_disk_path=disk_path,
            yandex_disk_uploaded_at=timezone.now(),
            yandex_disk_error="",
        )
        item = FamilyIncomeDocument.objects.create(
            case=case,
            document=document,
            category=category,
            candidate_comment=title,
            added_by=request.user,
        )
        _save_evidence(item, category, form.cleaned_data)
    messages.success(request, "Документ добавлен. Когда закончите заполнение, отправьте карточку на проверку.")
    return redirect("family_income:page")


@login_required
@require_POST
def submit_case(request):
    case = _case_for_user(request.user)
    if not _is_editable(case):
        messages.error(request, "Карточка уже отправлена на проверку.")
        return redirect("family_income:page")

    completion = _completion(case)
    errors = []
    if not completion["family_complete"]:
        errors.append("заполните состав семьи")
    if completion["unresolved_clarifications_count"]:
        errors.append("сохраните изменения по документам, по которым запрошено уточнение")
    if errors:
        messages.error(request, "Перед отправкой: " + "; ".join(errors) + ".")
        return redirect("family_income:page")

    is_resubmission = case.family_income_documents.filter(
        review_status=FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
    ).exists()
    candidate_name = request.user.get_full_name().strip() or request.user.username
    submission_word = "повторно отправил" if is_resubmission else "отправил"

    with transaction.atomic():
        case.family_income_documents.filter(
            review_status=FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
        ).update(review_status=FamilyIncomeDocument.ReviewStatus.PENDING, updated_at=timezone.now())
        case.status = FamilyIncomeCase.Status.PENDING_REVIEW
        case.save(update_fields=("status", "updated_at"))
        create_family_income_notification(
            recipients=active_staff_users(exclude_user_id=request.user.pk),
            sender=request.user,
            message=(
                f"Соискатель «{candidate_name}» {submission_word} карточку "
                "«Семья и доход» на проверку."
            ),
        )
    messages.success(request, "Сведения отправлены на проверку. Сообщим, если потребуется уточнение.")
    return redirect("family_income:page")


@login_required
def edit_document(request, document_id):
    case = _case_for_user(request.user)
    item = get_object_or_404(FamilyIncomeDocument, pk=document_id, case=case)
    if not _is_editable(case):
        messages.error(request, "Данные документа доступны только для просмотра.")
        return redirect("family_income:page")
    if item.review_status == FamilyIncomeDocument.ReviewStatus.APPROVED:
        messages.error(request, "Подтверждённый документ нельзя изменить. Обратитесь к сотруднику Фонда.")
        return redirect("family_income:page")
    try:
        form = document_form_for_category(
            item.category,
            request.POST or None,
            request.FILES or None,
            prefix=item.category,
            evidence=_document_evidence(item),
            require_file=False,
        )
    except ValueError as exc:
        raise Http404("Неизвестная категория документа.") from exc
    if request.method == "POST":
        if not form.is_valid():
            messages.error(request, "Проверьте введённые данные.")
        else:
            title = _document_title(item.category, form.cleaned_data)
            uploaded_file = form.cleaned_data.get("file")
            if uploaded_file:
                uploaded_file, upload_errors = _validate_upload(uploaded_file, title)
                if upload_errors:
                    for errors in upload_errors.values():
                        for error in errors:
                            messages.error(request, error)
                    return render(request, "family_income/edit_document.html", {"form": form, "item": item, "active": "family_income"}, status=400)
                try:
                    disk_path = _upload_to_disk(request.user, uploaded_file)
                except YandexDiskError:
                    logger.exception("Family-income document replacement failed for user_id=%s document_id=%s", request.user.id, item.document_id)
                    messages.error(request, "Не удалось загрузить новый файл на Яндекс Диск. Попробуйте ещё раз.")
                    return render(request, "family_income/edit_document.html", {"form": form, "item": item, "active": "family_income"}, status=502)
                old_disk_path = item.document.yandex_disk_path
                item.document.user_file_name = uploaded_file.name
                item.document.yandex_disk_path = disk_path
                item.document.yandex_disk_uploaded_at = timezone.now()
                item.document.yandex_disk_error = ""
                item.document.save(update_fields=("user_file_name", "yandex_disk_path", "yandex_disk_uploaded_at", "yandex_disk_error"))
                if old_disk_path:
                    try:
                        delete_resource(old_disk_path, log_context={"user_id": request.user.id, "asset": "family_income"})
                    except YandexDiskError:
                        logger.warning("Could not remove replaced family-income file path=%s", old_disk_path)
            item.document.caption = title
            item.document.save(update_fields=("caption",))
            was_clarification = item.review_status == FamilyIncomeDocument.ReviewStatus.CLARIFICATION
            item.candidate_comment = title
            if was_clarification:
                item.candidate_response_at = timezone.now()
                item.save(update_fields=("candidate_comment", "candidate_response_at", "updated_at"))
            else:
                item.save(update_fields=("candidate_comment", "updated_at"))
            _save_evidence(item, item.category, form.cleaned_data)
            if was_clarification:
                messages.success(request, "Изменения сохранены. Отправьте карточку на проверку, когда исправите все замечания.")
            else:
                messages.success(request, "Данные документа сохранены.")
            return redirect("family_income:page")
    return render(request, "family_income/edit_document.html", {"form": form, "item": item, "active": "family_income"})


@login_required
@require_POST
def delete_document(request, document_id):
    case = _case_for_user(request.user)
    item = get_object_or_404(FamilyIncomeDocument, pk=document_id, case=case)
    if not _is_editable(case):
        messages.error(request, "Удаление документов сейчас недоступно.")
    elif item.review_status == FamilyIncomeDocument.ReviewStatus.APPROVED:
        messages.error(request, "Подтверждённый документ нельзя удалить. Обратитесь к сотруднику Фонда.")
    elif item.review_status == FamilyIncomeDocument.ReviewStatus.CLARIFICATION:
        messages.error(request, "По этому документу запрошено уточнение. Исправьте его или замените файл вместо удаления.")
    else:
        item.document.is_deleted = True
        item.document.save(update_fields=("is_deleted",))
        item.delete()
        messages.success(request, "Документ удалён.")
    return redirect("family_income:page")
