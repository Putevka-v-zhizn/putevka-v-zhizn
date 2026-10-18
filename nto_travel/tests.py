from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from core.models import RegistrationPersonalData, UserNotification
from scholar_form.models import UserInfo
from .models import (
    NtoApplication, NtoApplicationEvent, NtoApplicationProfile,
    NtoCampaign, NtoConsentRevision, NtoProfile, NtoProfileImport,
)
from .forms import FinanceForm, MotivationForm
from .services import (
    apply_profile_import, create_application, parse_profile_workbook,
    review_application, submit_application, validate_submission,
)


class NtoTravelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="nto@example.test", email="nto@example.test", password="testpass123")
        cls.other = get_user_model().objects.create_user(username="other@example.test", email="other@example.test", password="testpass123")
        cls.staff = get_user_model().objects.create_user(username="staff@example.test", email="staff@example.test", password="testpass123", is_staff=True)
        cls.consent = NtoConsentRevision.objects.create(version="test-1", text="Тестовый текст согласия")
        now = timezone.now()
        cls.campaign = NtoCampaign.objects.create(
            slug="test-season", academic_year="2099/2100", name="Сезон НТО",
            opens_at=now - timedelta(days=1), closes_at=now + timedelta(days=1),
            state=NtoCampaign.State.DRAFT, consent_revision=cls.consent,
        )
        cls.profile = NtoProfile.objects.create(campaign=cls.campaign, external_code="robot", name="Робототехника", final_city="Томск")
        cls.campaign.state = NtoCampaign.State.PUBLISHED
        cls.campaign.save(update_fields=["state"])

    def filled_application(self):
        app = create_application(self.user, self.campaign)
        for key, value in {
            "last_name": "Иванов", "first_name": "Иван", "region": "Томская область",
            "city": "Северск", "school_class": 10, "phone": "+79000000000",
            "email": self.user.email, "parent_name": "Иванова Мария", "parent_role": "мать",
            "parent_phone": "+79000000001", "finalist_declared": True,
            "parent_contact_declared": True, "previous_final": False,
            "previous_payers": [], "possible_payers": ["parents"],
            "school_support": "not_discussed", "parent_support": "partial",
            "ticket_cost": 1000, "income_disclosure": "declined",
            "family_material_status": UserInfo.FamilyMaterialStatus.values[0],
            "circumstances": ["none"], "universities": ["ТГУ"],
            "specializations": ["Информатика"], "no_achievements": True,
            "olympiad_plans": "Планирую НТО", "preparation_methods": ["self_study"],
            "preparation_details": "Занимаюсь еженедельно", "nto_goal": "Участие в финале",
            "refused_olympiads": False, "admission_without_trip": "Буду искать другие пути",
            "has_admission_advantages": False,
        }.items():
            setattr(app, key, value)
        app.save()
        NtoApplicationProfile.objects.get_or_create(application=app, profile=self.profile, defaults={"rank": 1})
        return app

    def test_unique_draft_and_submission_snapshot_notification(self):
        app = self.filled_application()
        self.assertEqual(create_application(self.user, self.campaign).pk, app.pk)
        submitted = submit_application(app.pk, self.user, consent_confirmed=True)
        self.assertEqual(submitted.status, NtoApplication.Status.SUBMITTED)
        self.assertEqual(submitted.final_city, "Томск")
        self.assertEqual(submitted.ranked_profiles.get().city_snapshot, "Томск")
        self.assertEqual(UserNotification.objects.filter(recipient=self.user).count(), 1)
        with self.assertRaises(ValidationError):
            submit_application(app.pk, self.user, consent_confirmed=True)
        self.assertEqual(NtoApplicationEvent.objects.filter(application=app, action="submitted").count(), 1)

    def test_conditional_answers_and_closed_campaign(self):
        app = self.filled_application()
        app.ticket_cost = 10000001
        with self.assertRaises(ValidationError):
            validate_submission(app)
        app.ticket_cost = 1000
        app.nto_goal = "x" * 2001
        with self.assertRaises(ValidationError):
            validate_submission(app)
        app.nto_goal = "Участие в финале"
        app.possible_payers = ["none", "parents"]
        app.save()
        with self.assertRaises(ValidationError):
            validate_submission(app)
        app.possible_payers = ["none"]
        app.circumstances = ["other"]
        app.save()
        with self.assertRaises(ValidationError):
            validate_submission(app)
        app.situation_details = "Стоимость поездки недоступна семье"
        app.save()
        with self.assertRaises(ValidationError):
            validate_submission(app)  # Не указан ответ о подтверждении обстоятельств.
        app.circumstance_proof = False
        app.save()
        validate_submission(app)
        self.campaign.closes_at = timezone.now() - timedelta(seconds=1)
        self.campaign.save()
        with self.assertRaises(ValidationError):
            submit_application(app.pk, self.user, consent_confirmed=True)

    def test_review_is_final_and_clarification_can_outlive_campaign(self):
        app = self.filled_application()
        submit_application(app.pk, self.user, consent_confirmed=True)
        due = timezone.now() + timedelta(days=3)
        review_application(app.pk, self.staff, "clarify", comment="Уточните поездку", due_at=due)
        self.campaign.closes_at = timezone.now() - timedelta(seconds=1)
        self.campaign.save()
        app = submit_application(app.pk, self.user, consent_confirmed=True)
        self.assertEqual(app.status, NtoApplication.Status.SUBMITTED)
        app = review_application(app.pk, self.staff, "reject", comment="Недостаточно средств программы")
        self.assertEqual(app.status, NtoApplication.Status.REJECTED)
        with self.assertRaises(ValidationError):
            review_application(app.pk, self.staff, "approve")
        self.assertEqual(UserNotification.objects.filter(recipient=self.user).count(), 4)

    def test_import_preview_and_repeat_keeps_snapshots(self):
        book = Workbook()
        sheet = book.active
        sheet.append(["external_code", "name", "final_city"])
        sheet.append(["robot", "Робототехника", "Москва"])
        sheet.append(["robot", "Робототехника", "Казань"])
        stream = BytesIO()
        book.save(stream)
        _, errors, _ = parse_profile_workbook(BytesIO(stream.getvalue()))
        self.assertTrue(errors)
        app = self.filled_application()
        submit_application(app.pk, self.user, consent_confirmed=True)
        batch = NtoProfileImport.objects.create(
            campaign=self.campaign, actor=self.staff, file_sha256="x" * 64,
            row_count=1, rows=[{"external_code": "robot", "name": "Роботы", "final_city": "Москва"}],
        )
        apply_profile_import(batch.pk, self.campaign, self.staff)
        self.assertEqual(NtoProfile.objects.get(pk=self.profile.pk).final_city, "Москва")
        self.assertEqual(app.ranked_profiles.get().city_snapshot, "Томск")

    def test_private_pages_permissions_and_xlsx(self):
        app = self.filled_application()
        app.last_name = "=FORMULA()"
        app.save(update_fields=["last_name"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("nto_travel:review", args=[self.campaign.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "mc.yandex.ru")
        self.assertEqual(self.client.get(reverse("nto_staff:queue")).status_code, 403)
        self.client.force_login(self.staff)
        reviewer = Group.objects.get(name="Проверяющий НТО")
        self.staff.groups.add(reviewer)
        self.assertEqual(self.client.get(reverse("nto_staff:queue")).status_code, 200)
        detail = self.client.get(reverse("nto_staff:detail", args=[self.campaign.slug, app.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "mc.yandex.ru")
        self.assertEqual(NtoApplicationEvent.objects.filter(application=app, action="staff_view").count(), 1)
        self.assertEqual(self.client.get(reverse("nto_staff:export", args=[self.campaign.slug])).status_code, 403)
        administrator = Group.objects.get(name="Администратор НТО")
        self.staff.groups.add(administrator)
        self.staff = get_user_model().objects.get(pk=self.staff.pk)
        template = self.client.get(reverse("nto_staff:profile_template", args=[self.campaign.slug]))
        self.assertEqual(load_workbook(BytesIO(template.content)).active["A1"].value, "external_code")
        response = self.client.get(reverse("nto_staff:export", args=[self.campaign.slug]))
        self.assertEqual(response.status_code, 200)
        sheet = load_workbook(BytesIO(response.content)).active
        self.assertIn("'=FORMULA()", [cell.value for cell in sheet[2]])
        self.assertEqual(NtoApplicationEvent.objects.filter(application=app, action="export").count(), 1)
        filtered = self.client.get(reverse("nto_staff:export", args=[self.campaign.slug]), {"status": "submitted"})
        self.assertEqual(load_workbook(BytesIO(filtered.content)).active.max_row, 1)

    def test_incomplete_draft_and_conditional_form_cleanup(self):
        self.client.force_login(self.user)
        url = reverse("nto_travel:apply_step", args=[self.campaign.slug, "personal"])
        response = self.client.post(url, {
            "first_name": "Иван", "choose_%s" % self.profile.pk: "on",
            "rank_%s" % self.profile.pk: "1",
        })
        self.assertEqual(response.status_code, 302)
        app = NtoApplication.objects.get(user=self.user, campaign=self.campaign)
        self.assertEqual(app.status, NtoApplication.Status.DRAFT)
        self.assertEqual(app.ranked_profiles.count(), 1)
        self.assertEqual(app.email, self.user.email)
        response = self.client.post(reverse("nto_travel:apply_step", args=[self.campaign.slug, "finance"]), {
            "previous_final": "no", "previous_payers": ["region"],
            "income_disclosure": "declined", "income_per_member": "1000", "income_proof": "yes",
            "circumstances": ["none"], "circumstance_proof": "yes",
        })
        self.assertEqual(response.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.previous_payers, [])
        self.assertIsNone(app.income_per_member)
        self.assertIsNone(app.income_proof)
        self.assertIsNone(app.circumstance_proof)
        self.assertEqual(FinanceForm(instance=app)["previous_final"].value(), "no")
        self.assertEqual(MotivationForm(instance=app)["refused_olympiads"].value(), "")

    def test_other_user_cannot_read_application(self):
        self.filled_application()
        self.client.force_login(self.other)
        response = self.client.get(reverse("nto_travel:application", args=[self.campaign.slug]))
        self.assertEqual(response.status_code, 404)

    def test_program_navigation_is_separate(self):
        info = UserInfo.objects.create(user=self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("index"))
        self.assertContains(response, 'id="selectionMenu"')
        self.assertContains(response, 'id="selectionDropdown"')
        self.assertNotContains(response, 'href="' + reverse("nto_travel:landing") + '"')
        RegistrationPersonalData.objects.create(
            user=self.user, email=self.user.email, password=self.user.password,
            current_step="finish", nto_campaign_slug=self.campaign.slug,
        )
        response = self.client.get(reverse("index"))
        self.assertContains(response, 'href="' + reverse("nto_travel:landing") + '"')
        for main_url in ("apply", "candidate_testing_list", "motivation_letter", "my_video_page", "preparation"):
            self.assertNotContains(response, 'href="' + reverse(main_url) + '"')
        self.assertNotContains(response, 'id="selectionMenu"')
        self.assertNotContains(response, 'id="selectionDropdown"')
        self.assertNotContains(response, "Как проходит отбор")
        self.assertNotContains(response, "ещё не отправлена")
        info.form_status = "submitted"
        info.status = "FINAL STAGE"
        info.save(update_fields=["form_status", "status"])
        response = self.client.get(reverse("index"))
        self.assertContains(response, 'href="' + reverse("nto_travel:landing") + '"')
        self.assertNotContains(response, 'href="' + reverse("family_income:page") + '"')
        self.assertNotContains(response, 'href="' + reverse("documents_dashboard") + '"')

    def test_rendered_answers_and_submission_errors_are_visible(self):
        app = self.filled_application()
        self.assertEqual(FinanceForm(instance=app)["previous_final"].value(), "no")
        self.assertEqual(MotivationForm(instance=app)["refused_olympiads"].value(), "no")
        self.client.force_login(self.user)
        finance = self.client.get(reverse("nto_travel:apply_step", args=[self.campaign.slug, "finance"]))
        self.assertContains(finance, '<option value="no" selected>Нет</option>', html=True)
        app.nto_goal = ""
        app.save(update_fields=["nto_goal"])
        response = self.client.post(reverse("nto_travel:submit", args=[self.campaign.slug]), {"accept_consent": "on"}, follow=True)
        self.assertContains(response, "Цель участия в НТО: Обязательный ответ")
        self.assertContains(response, "Город финала")
        self.assertContains(response, "Томск")
        app.status = "clarification"
        app.clarification_due_at = timezone.now() + timedelta(days=1)
        app.public_comment = "Пожалуйста, уточните план поездки."
        app.save()
        response = self.client.get(reverse("nto_travel:apply_step", args=[self.campaign.slug, "personal"]))
        self.assertContains(response, app.public_comment)

    @patch("core.views.send_email_verification_code")
    def test_registration_remembers_nto_destination(self, mocked_email):
        url = reverse("register_initial") + "?nto=" + self.campaign.slug
        response = self.client.get(url)
        self.assertContains(response, f'name="nto" value="{self.campaign.slug}"')
        response = self.client.post(reverse("register_initial"), {
            "nto": self.campaign.slug,
            "email": "new-nto@example.test",
            "password": "StrongTestPassword2026!",
            "password_confirm": "StrongTestPassword2026!",
        })
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(email="new-nto@example.test")
        self.assertEqual(user.registrationpersonaldata.nto_campaign_slug, self.campaign.slug)
        mocked_email.assert_called_once()
        user.registrationpersonaldata.current_step = "finish"
        user.registrationpersonaldata.save(update_fields=["current_step"])
        response = self.client.get(reverse("finish_registration"))
        self.assertContains(response, reverse("nto_travel:apply_step", args=[self.campaign.slug, "personal"]))
