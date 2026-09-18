from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from review_by_tutor.views import _staff_check
from scholar_form.models import UserInfo

from .forms import (
    FamilyIncomeCaseStaffForm,
    FamilyIncomeDocumentReviewForm,
    IncomeEvidenceStaffForm,
    FamilyIncomeDecisionForm,
)
from .models import FamilyIncomeCase, FamilyIncomeDocument, FamilyIncomeDecision, FamilyIncomeAuditEvent
from .notifications import create_family_income_notification

User = get_user_model()


def _case_for_staff(user):
    user_info, _ = UserInfo.objects.get_or_create(user=user)
    return FamilyIncomeCase.objects.get_or_create(
        user_info=user_info,
        defaults={
            "family_members_count": 1,
            "family_members_description": "",
            "status": FamilyIncomeCase.Status.STAFF_DRAFT,
        },
    )[0]


def _document_sections(case, *, review_form_with_error=None, income_form_with_error=None):
    documents = (
        case.family_income_documents.select_related(
            "document", "income_evidence", "social_benefit_evidence"
        )
        .order_by("category", "-created_at")
    )
    items_by_category = {
        category: [] for category, _ in FamilyIncomeDocument.Category.choices
    }
    for item in documents:
        review_form = (
            review_form_with_error
            if review_form_with_error and review_form_with_error.instance.pk == item.pk
            else FamilyIncomeDocumentReviewForm(instance=item, prefix=f"review-{item.pk}")
        )
        income_evidence = getattr(item, "income_evidence", None)
        income_form = None
        if income_evidence:
            income_form = (
                income_form_with_error
                if income_form_with_error
                and income_form_with_error.instance.pk == income_evidence.pk
                else IncomeEvidenceStaffForm(
                    instance=income_evidence,
                    prefix=f"income-{item.pk}",
                )
            )
        items_by_category[item.category].append({
            "item": item,
            "review_form": review_form,
            "income_form": income_form,
        })

    return [
        {
            "category": category,
            "label": label,
            "items": items_by_category[category],
        }
        for category, label in FamilyIncomeDocument.Category.choices
    ]


def _render_page(
    request,
    *,
    user_obj,
    case,
    case_form=None,
    review_form_with_error=None,
    income_form_with_error=None,
    decision_form=None,
    status=200,
):
    return render(
        request,
        "family_income/staff_page.html",
        {
            "user_obj": user_obj,
            "case": case,
            "case_form": case_form or FamilyIncomeCaseStaffForm(instance=case),
            "sections": _document_sections(
                case,
                review_form_with_error=review_form_with_error,
                income_form_with_error=income_form_with_error,
            ),
            "active": "family_income_staff",
            "decision_form": decision_form if decision_form is not None else FamilyIncomeDecisionForm(
                case=case, initial=case.decisions.filter(year__isnull=True).values("amount_per_member", "comment").first(),
            ),
            "unapproved_documents_count": case.family_income_documents.exclude(
                review_status=FamilyIncomeDocument.ReviewStatus.APPROVED,
            ).count(),
        },
        status=status,
    )


@login_required
@user_passes_test(_staff_check)
@transaction.atomic
def staff_family_income(request, user_id: int):
    """Служебная часть карточки «Семья и доход» конкретного участника."""
    user_obj = get_object_or_404(User, pk=user_id)
    case = _case_for_staff(user_obj)

    if request.method != "POST":
        return _render_page(request, user_obj=user_obj, case=case)

    form_type = request.POST.get("form_type")
    if form_type == "save_decision":
        # Serialize updates for a case, including creation of its current result.
        case = FamilyIncomeCase.objects.select_for_update().get(pk=case.pk)
        form = FamilyIncomeDecisionForm(request.POST, case=case)
        if not form.is_valid():
            return _render_page(request, user_obj=user_obj, case=case, decision_form=form, status=400)
        decision = FamilyIncomeDecision.objects.filter(case=case, year__isnull=True).first()
        before = {} if decision is None else {
            "amount_per_member": str(decision.amount_per_member) if decision.amount_per_member is not None else None,
            "comment": decision.comment,
        }
        if decision is None:
            decision = FamilyIncomeDecision(case=case, created_by=request.user)
        decision.amount_per_member = form.cleaned_data["amount_per_member"]
        decision.comment = form.cleaned_data["comment"]
        decision.updated_by = request.user
        decision.save()
        FamilyIncomeAuditEvent.objects.create(
            case=case, actor=request.user, action="save_decision",
            target_model="FamilyIncomeDecision", target_id=decision.pk,
            before=before,
            after={"amount_per_member": str(decision.amount_per_member), "comment": decision.comment},
            reason=decision.comment,
        )
        messages.success(request, "Итоговый доход сохранён.")
        return redirect("staff_family_income", user_id=user_obj.pk)

    if form_type == "reopen_case":
        case = FamilyIncomeCase.objects.select_for_update().get(pk=case.pk)
        if case.status != FamilyIncomeCase.Status.APPROVED:
            messages.error(request, "Вернуть на проверку можно только подтверждённую карточку.")
            return redirect("staff_family_income", user_id=user_obj.pk)
        previous_status = case.status
        case.status = FamilyIncomeCase.Status.PENDING_REVIEW
        case.save(update_fields=("status", "updated_at"))
        FamilyIncomeAuditEvent.objects.create(
            case=case, actor=request.user, action="reopen_case",
            target_model="FamilyIncomeCase", target_id=case.pk,
            before={"status": previous_status}, after={"status": case.status},
        )
        messages.success(request, "Карточка возвращена на проверку.")
        return redirect("staff_family_income", user_id=user_obj.pk)

    if form_type == "update_case":
        case_form = FamilyIncomeCaseStaffForm(request.POST, instance=case)
        if case_form.is_valid():
            case_form.save()
            messages.success(request, "Состав и характеристика семьи сохранены.")
            return redirect("staff_family_income", user_id=user_obj.pk)
        messages.error(request, "Проверьте сведения о семье.")
        return _render_page(
            request,
            user_obj=user_obj,
            case=case,
            case_form=case_form,
            status=400,
        )

    if form_type == "approve_case":
        if case.status != FamilyIncomeCase.Status.PENDING_REVIEW:
            messages.error(request, "Подтвердить можно только карточку, которая находится на проверке.")
            return redirect("staff_family_income", user_id=user_obj.pk)

        unapproved_documents_count = case.family_income_documents.exclude(
            review_status=FamilyIncomeDocument.ReviewStatus.APPROVED,
        ).count()
        if unapproved_documents_count:
            messages.error(
                request,
                "Сначала завершите проверку всех документов: "
                f"осталось {unapproved_documents_count}.",
            )
            return redirect("staff_family_income", user_id=user_obj.pk)

        case.status = FamilyIncomeCase.Status.APPROVED
        case.save(update_fields=("status", "updated_at"))
        create_family_income_notification(
            recipients=[user_obj],
            sender=request.user,
            message=(
                "Карточка «Семья и доход» проверена и подтверждена. "
                "Спасибо за предоставленные сведения."
            ),
        )
        messages.success(request, "Карточка подтверждена. Соискателю отправлено уведомление.")
        return redirect("staff_family_income", user_id=user_obj.pk)

    document_id = request.POST.get("document_id")
    item = get_object_or_404(
        FamilyIncomeDocument.objects.select_related("income_evidence"),
        pk=document_id,
        case=case,
    )
    if form_type == "update_document_review":
        previous_status = item.review_status
        previous_comment = item.staff_comment
        form = FamilyIncomeDocumentReviewForm(
            request.POST,
            instance=item,
            prefix=f"review-{item.pk}",
        )
        if form.is_valid():
            item = form.save()
            if item.review_status == FamilyIncomeDocument.ReviewStatus.CLARIFICATION:
                if case.status != FamilyIncomeCase.Status.REVISION:
                    case.status = FamilyIncomeCase.Status.REVISION
                    case.save(update_fields=("status", "updated_at"))
                is_new_clarification = (
                    previous_status != FamilyIncomeDocument.ReviewStatus.CLARIFICATION
                    or previous_comment != item.staff_comment
                )
                if is_new_clarification:
                    item.clarification_requested_at = timezone.now()
                    item.candidate_response_at = None
                    item.save(update_fields=(
                        "clarification_requested_at",
                        "candidate_response_at",
                    ))
                    document_name = item.document.user_file_name or item.document.caption
                    create_family_income_notification(
                        recipients=[user_obj],
                        sender=request.user,
                        message=(
                            "В разделе «Семья и доход» нужно уточнить сведения "
                            f"по документу «{document_name}». Откройте раздел, "
                            "прочитайте комментарий и внесите изменения."
                        ),
                    )
                    messages.success(
                        request,
                        "Запрошено уточнение: карточка возвращена соискателю на доработку, "
                        "уведомление отправлено.",
                    )
                    return redirect("staff_family_income", user_id=user_obj.pk)
            messages.success(request, "Статус документа и служебный комментарий сохранены.")
            return redirect("staff_family_income", user_id=user_obj.pk)
        messages.error(request, "Проверьте статус документа и служебный комментарий.")
        return _render_page(
            request,
            user_obj=user_obj,
            case=case,
            review_form_with_error=form,
            status=400,
        )

    if form_type == "update_income":
        evidence = getattr(item, "income_evidence", None)
        if item.category != FamilyIncomeDocument.Category.INCOME or not evidence:
            messages.error(request, "Сведения о доходе для этого документа не найдены.")
            return redirect("staff_family_income", user_id=user_obj.pk)
        form = IncomeEvidenceStaffForm(
            request.POST,
            instance=evidence,
            prefix=f"income-{item.pk}",
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Сведения о доходе сохранены.")
            return redirect("staff_family_income", user_id=user_obj.pk)
        messages.error(request, "Проверьте сведения о доходе.")
        return _render_page(
            request,
            user_obj=user_obj,
            case=case,
            income_form_with_error=form,
            status=400,
        )

    messages.error(request, "Неизвестное действие.")
    return redirect("staff_family_income", user_id=user_obj.pk)
