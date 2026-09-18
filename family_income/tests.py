from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import UserNotification
from documents.models import Document
from scholar_form.models import UserInfo

from .forms import IncomeDocumentForm, SocialBenefitDocumentForm
from .models import (
    FamilyIncomeCase, FamilyIncomeDecision, FamilyIncomeDocument, FamilyIncomeInstruction,
    IncomeEvidence, IncomeYear,
    SocialBenefitEvidence,
)


class FamilyIncomeUserFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finalist", password="password")
        self.info = UserInfo.objects.create(user=self.user, status="FINAL STAGE")
        self.client.force_login(self.user)
        self.year, _ = IncomeYear.objects.get_or_create(year=2025)

    def _case(self):
        return FamilyIncomeCase.objects.get(user_info=self.info)

    def _other_document(self, *, review_status=FamilyIncomeDocument.ReviewStatus.PENDING):
        case = self._case()
        document = Document.objects.create(
            user=self.user,
            caption="Справка",
            user_file_name="old.pdf",
            yandex_disk_path="disk:/documents/old.pdf",
        )
        return FamilyIncomeDocument.objects.create(
            case=case,
            document=document,
            category=FamilyIncomeDocument.Category.OTHER,
            candidate_comment="Справка",
            review_status=review_status,
        )

    def _document_for_category(self, category):
        case = self._case()
        document = Document.objects.create(user=self.user, caption=category, yandex_disk_path=f"disk:/{category}.pdf")
        return FamilyIncomeDocument.objects.create(
            case=case,
            document=document,
            category=category,
            candidate_comment=category,
        )

    def test_finalist_can_open_page_and_non_finalist_cannot(self):
        response = self.client.get(reverse("family_income:page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Состав семьи")

        other = User.objects.create_user(username="candidate", password="password")
        UserInfo.objects.create(user=other, status="CANDIDATE")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("family_income:page")).status_code, 404)

    def test_only_active_instruction_is_shown_to_finalist(self):
        draft = FamilyIncomeInstruction.objects.create(
            version="draft-1",
            title="Черновая инструкция",
            text="Этот текст не должен быть виден соискателю.",
        )
        response = self.client.get(reverse("family_income:page"))
        self.assertNotContains(response, draft.title)

        instruction = FamilyIncomeInstruction.objects.create(
            version="active-1",
            title="Инструкция по заполнению",
            text="Актуальные рекомендации для соискателя.",
            url="https://example.test/family-income-guide",
            status=FamilyIncomeInstruction.Status.PUBLISHED,
        )
        response = self.client.get(reverse("family_income:page"))
        self.assertContains(response, instruction.title)
        self.assertContains(response, instruction.text)
        self.assertContains(response, instruction.url)

        instruction.url = ""
        instruction.file = "family_income/instructions/guide.pdf"
        instruction.save()
        response = self.client.get(reverse("family_income:page"))
        self.assertContains(response, instruction.file.url)

    def test_admin_can_create_active_instruction_without_technical_version(self):
        administrator = User.objects.create_superuser(
            username="instruction-admin",
            email="admin@example.test",
            password="password",
        )
        self.client.force_login(administrator)

        response = self.client.post(
            reverse("admin:family_income_familyincomeinstruction_add"),
            {
                "title": "Инструкция",
                "text": "Текст инструкции.",
                "url": "",
                "status": FamilyIncomeInstruction.Status.PUBLISHED,
                "_save": "Сохранить",
            },
        )

        self.assertEqual(response.status_code, 302)
        instruction = FamilyIncomeInstruction.objects.get()
        self.assertTrue(instruction.version)
        self.assertEqual(instruction.updated_by, administrator)

    def test_income_allows_empty_amounts(self):
        form = IncomeDocumentForm(
            data={"income-year": self.year.pk, "income-owner_name": "Мама"},
            files={"income-file": SimpleUploadedFile("income.pdf", b"%PDF-1.4")},
            prefix="income",
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_social_benefit_description_is_optional(self):
        form = SocialBenefitDocumentForm(
            data={"social_benefit-recipient_name": "Мама"},
            files={"social_benefit-file": SimpleUploadedFile("benefit.pdf", b"%PDF-1.4")},
            prefix="social_benefit",
        )
        self.assertTrue(form.is_valid(), form.errors)

    @patch("family_income.views.upload_file_to_yandex_disk")
    @patch("documents.forms.magic.from_buffer", return_value="application/pdf", create=True)
    def test_income_document_creates_metadata(self, _mime, _upload):
        response = self.client.post(
            reverse("family_income:add_document", args=[FamilyIncomeDocument.Category.INCOME]),
            {
                "income-file": SimpleUploadedFile("income.pdf", b"%PDF-1.4"),
                "income-year": self.year.pk,
                "income-owner_name": "Мама",
            },
        )
        self.assertRedirects(response, reverse("family_income:page"))
        evidence = IncomeEvidence.objects.get()
        self.assertEqual(evidence.year, self.year)
        self.assertEqual(evidence.owner_name, "Мама")
        self.assertIsNone(evidence.gross_amount)

    @patch("family_income.views.upload_file_to_yandex_disk")
    @patch("documents.forms.magic.from_buffer", return_value="application/pdf", create=True)
    def test_social_benefit_document_creates_metadata(self, _mime, _upload):
        response = self.client.post(
            reverse("family_income:add_document", args=[FamilyIncomeDocument.Category.SOCIAL_BENEFIT]),
            {
                "social_benefit-file": SimpleUploadedFile("benefit.pdf", b"%PDF-1.4"),
                "social_benefit-recipient_name": "Мама",
                "social_benefit-benefit_description": "Ежемесячное пособие",
            },
        )
        self.assertRedirects(response, reverse("family_income:page"))
        evidence = SocialBenefitEvidence.objects.get()
        self.assertEqual(evidence.recipient_name, "Мама")
        self.assertEqual(evidence.benefit_description, "Ежемесячное пособие")

    def test_user_cannot_access_another_family_document(self):
        self.client.get(reverse("family_income:page"))
        other = User.objects.create_user(username="other-finalist", password="password")
        other_info = UserInfo.objects.create(user=other, status="FINAL STAGE")
        other_case = FamilyIncomeCase.objects.create(
            user_info=other_info,
            family_members_count=2,
            family_members_description="Семья",
            status=FamilyIncomeCase.Status.REVISION,
        )
        document = Document.objects.create(user=other, caption="Чужой", yandex_disk_path="disk:/other.pdf")
        item = FamilyIncomeDocument.objects.create(
            case=other_case,
            document=document,
            category=FamilyIncomeDocument.Category.OTHER,
            candidate_comment="Чужой",
        )
        self.assertEqual(self.client.get(reverse("family_income:edit_document", args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("family_income:delete_document", args=[item.pk])).status_code, 404)

    def test_confirmed_document_is_not_deleted(self):
        self.client.get(reverse("family_income:page"))
        item = self._other_document(review_status=FamilyIncomeDocument.ReviewStatus.APPROVED)
        response = self.client.post(reverse("family_income:delete_document", args=[item.pk]))
        self.assertRedirects(response, reverse("family_income:page"))
        self.assertTrue(FamilyIncomeDocument.objects.filter(pk=item.pk).exists())

    def test_user_can_delete_own_pending_document(self):
        self.client.get(reverse("family_income:page"))
        item = self._other_document()
        response = self.client.post(reverse("family_income:delete_document", args=[item.pk]))
        self.assertRedirects(response, reverse("family_income:page"))
        self.assertFalse(FamilyIncomeDocument.objects.filter(pk=item.pk).exists())
        item.document.refresh_from_db()
        self.assertTrue(item.document.is_deleted)

    def test_page_displays_link_to_user_document(self):
        self.client.get(reverse("family_income:page"))
        item = self._other_document()
        response = self.client.get(reverse("family_income:page"))
        self.assertContains(response, reverse("serve_document", args=[item.document_id]))

        with patch(
            "documents.views.get_download_url",
            return_value="https://download.example/family-income-document",
        ):
            response = self.client.get(reverse("serve_document", args=[item.document_id]))
        self.assertRedirects(
            response,
            "https://download.example/family-income-document",
            fetch_redirect_response=False,
        )

    def test_confirmed_document_is_not_editable(self):
        self.client.get(reverse("family_income:page"))
        item = self._other_document(review_status=FamilyIncomeDocument.ReviewStatus.APPROVED)
        response = self.client.get(reverse("family_income:edit_document", args=[item.pk]))
        self.assertRedirects(response, reverse("family_income:page"))

    def test_case_is_read_only_outside_revision(self):
        self.client.get(reverse("family_income:page"))
        case = self._case()
        case.status = FamilyIncomeCase.Status.PENDING_REVIEW
        case.save(update_fields=("status",))
        response = self.client.post(
            reverse("family_income:page"),
            {"family_members_count": 5, "family_members_description": "Новый состав", "family_characteristics": ""},
        )
        self.assertRedirects(response, reverse("family_income:page"))
        case.refresh_from_db()
        self.assertEqual(case.family_members_count, 1)

    def test_submit_requires_family_description(self):
        self.client.get(reverse("family_income:page"))
        response = self.client.post(reverse("family_income:submit"))
        self.assertRedirects(response, reverse("family_income:page"))
        self.assertEqual(self._case().status, FamilyIncomeCase.Status.REVISION)

    def test_submit_locks_case_without_documents(self):
        self.client.get(reverse("family_income:page"))
        case = self._case()
        case.family_members_description = "Мама работает, ребёнок учится"
        case.save(update_fields=("family_members_description",))
        response = self.client.post(reverse("family_income:submit"))
        self.assertRedirects(response, reverse("family_income:page"))
        case.refresh_from_db()
        self.assertEqual(case.status, FamilyIncomeCase.Status.PENDING_REVIEW)

    def test_submission_notifies_active_staff(self):
        staff = User.objects.create_user(username="family-income-staff", password="password", is_staff=True)
        self.client.get(reverse("family_income:page"))
        case = self._case()
        case.family_members_description = "Мама работает, ребёнок учится"
        case.save(update_fields=("family_members_description",))

        response = self.client.post(reverse("family_income:submit"))

        self.assertRedirects(response, reverse("family_income:page"))
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=staff,
                notification__message__contains="отправил карточку",
            ).exists()
        )

    @patch("family_income.views.delete_resource")
    @patch("family_income.views.upload_file_to_yandex_disk")
    @patch("documents.forms.magic.from_buffer", return_value="application/pdf", create=True)
    def test_edit_replaces_file(self, _mime, _upload, _delete):
        self.client.get(reverse("family_income:page"))
        item = self._other_document()
        response = self.client.post(
            reverse("family_income:edit_document", args=[item.pk]),
            {
                "other-file": SimpleUploadedFile("new.pdf", b"%PDF-1.4"),
                "other-candidate_comment": "Новая справка",
            },
        )
        self.assertRedirects(response, reverse("family_income:page"))
        item.document.refresh_from_db()
        self.assertEqual(item.document.user_file_name, "new.pdf")
        self.assertEqual(item.document.caption, "Новая справка")


class FamilyIncomeStaffViewTests(TestCase):
    def _save_decision(self, **overrides):
        data = {"form_type": "save_decision",
                "amount_per_member": "1234.50", "comment": "Ручной расчёт"}
        data.update(overrides)
        return self.client.post(reverse("staff_family_income", args=[self.candidate.pk]), data)

    def test_manual_results_in_all_statuses_and_audit(self):
        self.client.force_login(self.staff)
        for status in FamilyIncomeCase.Status.values:
            self.case.status = status
            self.case.save()
            self.assertEqual(self._save_decision().status_code, 302)
            self.case.refresh_from_db()
            self.assertEqual(self.case.status, status)
        self.assertEqual(self.case.decisions.count(), 1)
        decision = self.case.decisions.get()
        self.assertEqual(decision.created_by, self.staff)
        editor = User.objects.create_user(username="second-editor", is_staff=True)
        self.client.force_login(editor)
        self.assertEqual(self._save_decision(amount_per_member="0").status_code, 302)
        decision.refresh_from_db()
        self.assertEqual(decision.amount_per_member, 0)
        self.assertEqual(decision.created_by, self.staff)
        self.assertEqual(decision.updated_by, editor)
        event = self.case.audit_events.first()
        self.assertEqual(event.before["amount_per_member"], "1234.50")
        self.assertEqual(event.actor, editor)
        other_year, _ = IncomeYear.objects.get_or_create(year=2026)
        self._save_decision(year=other_year.pk)
        self.assertEqual(self.case.decisions.count(), 1)
        self.assertIsNone(self.case.decisions.get().year_id)

    def test_invalid_manual_result_and_form_without_year(self):
        self.client.force_login(self.staff)
        for overrides in ({"amount_per_member": ""}, {"amount_per_member": "-1"},
                          {"amount_per_member": "1.234"}, {"comment": "  "}):
            response = self._save_decision(**overrides)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.context["decision_form"].errors)
        self.assertEqual(self.case.decisions.count(), 0)
        self.assertEqual(self.case.audit_events.count(), 0)
        self.assertEqual(self._save_decision().status_code, 302)
        response = self.client.get(reverse("staff_family_income", args=[self.candidate.pk]))
        self.assertNotIn("year", response.context["decision_form"].fields)
        self.assertEqual(response.context["decision_form"].initial["comment"], "Ручной расчёт")

    def test_reopen_preserves_data_and_allows_reapproval(self):
        self.client.force_login(self.staff)
        self._save_decision()
        item = self._document(FamilyIncomeDocument.Category.OTHER)
        item.review_status = FamilyIncomeDocument.ReviewStatus.APPROVED
        item.save()
        self.case.status = FamilyIncomeCase.Status.APPROVED
        self.case.save()
        url = reverse("staff_family_income", args=[self.candidate.pk])
        response = self.client.get(url)
        self.assertContains(response, "Вернуть на проверку")
        self.assertContains(response, "Сохранить сведения о семье")
        notifications_before = UserNotification.objects.count()
        self.assertEqual(self.client.post(url, {"form_type": "reopen_case"}).status_code, 302)
        self.case.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.PENDING_REVIEW)
        self.assertEqual(item.review_status, FamilyIncomeDocument.ReviewStatus.APPROVED)
        self.assertEqual(self.case.decisions.count(), 1)
        self.assertEqual(UserNotification.objects.count(), notifications_before)
        self.assertEqual(self.case.audit_events.first().action, "reopen_case")
        self.assertContains(self.client.get(url), "Подтвердить карточку")
        self.client.post(url, {"form_type": "approve_case"})
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.APPROVED)

    def test_reopen_only_approved_and_results_private(self):
        url = reverse("staff_family_income", args=[self.candidate.pk])
        self.client.force_login(self.staff)
        for status in (FamilyIncomeCase.Status.REVISION, FamilyIncomeCase.Status.STAFF_DRAFT,
                       FamilyIncomeCase.Status.PENDING_REVIEW):
            self.case.status = status
            self.case.save()
            self.client.post(url, {"form_type": "reopen_case"})
            self.case.refresh_from_db()
            self.assertEqual(self.case.status, status)
        self.assertEqual(self.case.audit_events.count(), 0)
        self._save_decision(comment="Секретное пояснение итога")
        self.client.force_login(self.candidate)
        response = self.client.get(reverse("family_income:page"))
        self.assertNotContains(response, "Секретное пояснение итога")
        self.assertFalse(response.context["editable"])
        self.assertEqual(self._save_decision().status_code, 302)
        self.assertEqual(self.client.post(url, {"form_type": "reopen_case"}).status_code, 302)
        self.assertEqual(self.case.audit_events.count(), 1)

    def setUp(self):
        self.staff = User.objects.create_user(
            username="staff", password="password", is_staff=True
        )
        self.candidate = User.objects.create_user(
            username="finalist-for-review", password="password"
        )
        self.info = UserInfo.objects.create(user=self.candidate, status="FINAL STAGE")
        self.case = FamilyIncomeCase.objects.create(
            user_info=self.info,
            family_members_count=3,
            family_members_description="Мама, папа и ребёнок",
            family_characteristics="Полная семья",
            status=FamilyIncomeCase.Status.PENDING_REVIEW,
        )
        self.year, _ = IncomeYear.objects.get_or_create(year=2025)

    def _document(self, category, *, comment="Комментарий"):
        document = Document.objects.create(
            user=self.candidate,
            caption=comment,
            user_file_name="proof.pdf",
            yandex_disk_path="disk:/family-income/proof.pdf",
        )
        return FamilyIncomeDocument.objects.create(
            case=self.case,
            document=document,
            category=category,
            candidate_comment=comment,
        )

    def test_staff_can_review_family_and_income_documents(self):
        income_document = self._document(FamilyIncomeDocument.Category.INCOME, comment="Доход мамы")
        evidence = IncomeEvidence.objects.create(
            family_income_document=income_document,
            year=self.year,
            owner_name="Мама",
        )
        other_document = self._document(FamilyIncomeDocument.Category.OTHER, comment="Дополнительная справка")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("staff_family_income", args=[self.candidate.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Состав и характеристика семьи")
        self.assertContains(response, "Подтверждение статуса")
        self.assertContains(response, "Доход")
        self.assertContains(response, reverse("serve_document", args=[income_document.document_id]))
        self.assertContains(response, reverse("serve_document", args=[other_document.document_id]))

        response = self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {
                "form_type": "update_case",
                "family_members_count": 4,
                "family_members_description": "Мама, папа, ребёнок и бабушка",
                "family_characteristics": "Нуждается в поддержке",
            },
        )
        self.assertRedirects(response, reverse("staff_family_income", args=[self.candidate.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.family_members_count, 4)
        self.assertEqual(self.case.family_characteristics, "Нуждается в поддержке")

        income_prefix = f"income-{income_document.pk}"
        response = self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {
                "form_type": "update_income",
                "document_id": income_document.pk,
                f"{income_prefix}-year": self.year.pk,
                f"{income_prefix}-owner_name": "Мама",
                f"{income_prefix}-gross_amount": "120000",
                f"{income_prefix}-net_amount": "104400",
                f"{income_prefix}-average_monthly_amount": "8700",
                f"{income_prefix}-months_received": "12",
                f"{income_prefix}-absence_reason": "",
                f"{income_prefix}-staff_decision_comment": "Учесть в расчёте",
            },
        )
        self.assertRedirects(response, reverse("staff_family_income", args=[self.candidate.pk]))
        evidence.refresh_from_db()
        self.assertEqual(str(evidence.gross_amount), "120000.00")
        self.assertEqual(evidence.staff_decision_comment, "Учесть в расчёте")

        review_prefix = f"review-{income_document.pk}"
        response = self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {
                "form_type": "update_document_review",
                "document_id": income_document.pk,
                f"{review_prefix}-review_status": FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
                f"{review_prefix}-staff_comment": "Нужна более читаемая справка.",
            },
        )
        self.assertRedirects(response, reverse("staff_family_income", args=[self.candidate.pk]))
        income_document.refresh_from_db()
        self.assertEqual(
            income_document.review_status,
            FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
        )
        self.assertEqual(income_document.staff_comment, "Нужна более читаемая справка.")
        self.assertIsNotNone(income_document.clarification_requested_at)
        self.assertIsNone(income_document.candidate_response_at)
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.REVISION)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.candidate,
                notification__message__contains="Семья и доход",
            ).exists()
        )

    def test_clarification_returns_case_to_candidate_and_resubmits_document(self):
        item = self._document(FamilyIncomeDocument.Category.OTHER, comment="Справка")
        self.client.force_login(self.staff)
        review_prefix = f"review-{item.pk}"
        response = self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {
                "form_type": "update_document_review",
                "document_id": item.pk,
                f"{review_prefix}-review_status": FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
                f"{review_prefix}-staff_comment": "Загрузите более читаемую копию.",
            },
        )
        self.assertRedirects(response, reverse("staff_family_income", args=[self.candidate.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.REVISION)

        self.client.force_login(self.candidate)
        response = self.client.get(reverse("family_income:page"))
        self.assertContains(response, "Загрузите более читаемую копию.")
        self.assertContains(response, "Нужны уточнения")
        self.assertContains(response, "Отправить повторно на проверку")

        response = self.client.post(reverse("family_income:submit"))
        self.assertRedirects(response, reverse("family_income:page"))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.REVISION)
        item.refresh_from_db()
        self.assertEqual(item.review_status, FamilyIncomeDocument.ReviewStatus.CLARIFICATION)

        response = self.client.post(
            reverse("family_income:edit_document", args=[item.pk]),
            {"other-candidate_comment": "Загрузил исправленную копию."},
        )
        self.assertRedirects(response, reverse("family_income:page"))
        item.refresh_from_db()
        self.assertEqual(item.review_status, FamilyIncomeDocument.ReviewStatus.CLARIFICATION)
        self.assertIsNotNone(item.candidate_response_at)

        response = self.client.get(reverse("family_income:page"))
        self.assertContains(
            response,
            "Изменения сохранены — отправьте карточку на повторную проверку.",
        )

        response = self.client.post(reverse("family_income:submit"))
        self.assertRedirects(response, reverse("family_income:page"))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.PENDING_REVIEW)
        item.refresh_from_db()
        self.assertEqual(item.review_status, FamilyIncomeDocument.ReviewStatus.PENDING)

    def test_partial_corrections_do_not_allow_resubmission(self):
        first_item = self._document(FamilyIncomeDocument.Category.OTHER, comment="Первая справка")
        second_item = self._document(FamilyIncomeDocument.Category.OTHER, comment="Вторая справка")
        self.client.force_login(self.staff)
        for item in (first_item, second_item):
            review_prefix = f"review-{item.pk}"
            response = self.client.post(
                reverse("staff_family_income", args=[self.candidate.pk]),
                {
                    "form_type": "update_document_review",
                    "document_id": item.pk,
                    f"{review_prefix}-review_status": FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
                    f"{review_prefix}-staff_comment": "Уточните сведения в справке.",
                },
            )
            self.assertRedirects(response, reverse("staff_family_income", args=[self.candidate.pk]))

        self.client.force_login(self.candidate)
        response = self.client.post(
            reverse("family_income:edit_document", args=[first_item.pk]),
            {"other-candidate_comment": "Исправленная первая справка."},
        )
        self.assertRedirects(response, reverse("family_income:page"))

        response = self.client.post(reverse("family_income:submit"), follow=True)
        self.assertContains(response, "сохраните изменения по документам")
        self.case.refresh_from_db()
        first_item.refresh_from_db()
        second_item.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.REVISION)
        self.assertEqual(first_item.review_status, FamilyIncomeDocument.ReviewStatus.CLARIFICATION)
        self.assertEqual(second_item.review_status, FamilyIncomeDocument.ReviewStatus.CLARIFICATION)
        self.assertIsNotNone(first_item.candidate_response_at)
        self.assertIsNone(second_item.candidate_response_at)

    def test_staff_comment_change_reopens_saved_clarification(self):
        item = self._document(FamilyIncomeDocument.Category.OTHER)
        self.client.force_login(self.staff)
        review_prefix = f"review-{item.pk}"
        self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {
                "form_type": "update_document_review",
                "document_id": item.pk,
                f"{review_prefix}-review_status": FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
                f"{review_prefix}-staff_comment": "Уточните дату выдачи.",
            },
        )
        self.client.force_login(self.candidate)
        self.client.post(
            reverse("family_income:edit_document", args=[item.pk]),
            {"other-candidate_comment": "Дата выдачи указана."},
        )
        item.refresh_from_db()
        self.assertIsNotNone(item.candidate_response_at)

        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {
                "form_type": "update_document_review",
                "document_id": item.pk,
                f"{review_prefix}-review_status": FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
                f"{review_prefix}-staff_comment": "Уточните также номер справки.",
            },
        )
        self.assertRedirects(response, reverse("staff_family_income", args=[self.candidate.pk]))
        item.refresh_from_db()
        self.assertIsNone(item.candidate_response_at)
        self.assertIsNotNone(item.clarification_requested_at)

    def test_staff_can_approve_case_and_notifies_candidate(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {"form_type": "approve_case"},
        )

        self.assertRedirects(response, reverse("staff_family_income", args=[self.candidate.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.APPROVED)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.candidate,
                notification__message__contains="проверена и подтверждена",
            ).exists()
        )

    def test_staff_cannot_approve_case_with_unreviewed_documents(self):
        self._document(FamilyIncomeDocument.Category.OTHER)
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {"form_type": "approve_case"},
            follow=True,
        )

        self.assertContains(response, "Сначала завершите проверку всех документов")
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, FamilyIncomeCase.Status.PENDING_REVIEW)
        self.assertFalse(UserNotification.objects.filter(recipient=self.candidate).exists())

    def test_clarification_requires_staff_comment(self):
        item = self._document(FamilyIncomeDocument.Category.OTHER)
        self.client.force_login(self.staff)
        review_prefix = f"review-{item.pk}"
        response = self.client.post(
            reverse("staff_family_income", args=[self.candidate.pk]),
            {
                "form_type": "update_document_review",
                "document_id": item.pk,
                f"{review_prefix}-review_status": FamilyIncomeDocument.ReviewStatus.CLARIFICATION,
                f"{review_prefix}-staff_comment": "",
            },
        )
        self.assertEqual(response.status_code, 400)
        item.refresh_from_db()
        self.assertEqual(item.review_status, FamilyIncomeDocument.ReviewStatus.PENDING)

    def test_finalist_cannot_access_staff_route_or_internal_fields(self):
        income_document = self._document(FamilyIncomeDocument.Category.INCOME)
        IncomeEvidence.objects.create(
            family_income_document=income_document,
            year=self.year,
            owner_name="Мама",
            staff_decision_comment="Внутреннее решение",
        )
        income_document.staff_comment = "Только для сотрудников"
        income_document.save(update_fields=("staff_comment",))
        FamilyIncomeDecision.objects.create(
            case=self.case,
            year=self.year,
            amount_per_member="12345.67",
            comment="Ручная корректировка только для сотрудников",
        )

        self.client.force_login(self.candidate)
        response = self.client.get(reverse("staff_family_income", args=[self.candidate.pk]))
        self.assertEqual(response.status_code, 302)

        response = self.client.get(reverse("family_income:page"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Только для сотрудников")
        self.assertNotContains(response, "Внутреннее решение")
        self.assertNotContains(response, "Ручная корректировка только для сотрудников")
        self.assertNotContains(response, "12345.67")
