from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import Notification
from core.services.programs import select_program
from .forms import ReviewForm
from .models import NtoApplication, NtoApplicationEvent, NtoApplicationRead, NtoApplicationReview, NtoCampaign, NtoConsentRevision, NtoProfile
from .reviewing import ReviewConflict, mark_read, save_review
from .staff_views import _filtered
from .templatetags.nto_display import rubles


class NtoReviewingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.user = users.objects.create_user(username="candidate@example.test", email="candidate@example.test")
        cls.staff = users.objects.create_user(username="reviewer", first_name="Анна", last_name="Иванова", is_staff=True)
        cls.colleague = users.objects.create_user(username="colleague", is_staff=True)
        cls.viewer = users.objects.create_user(username="viewer", is_staff=True)
        for user in (cls.staff, cls.colleague):
            user.groups.add(Group.objects.get(name="Проверяющий НТО"))
        cls.viewer.user_permissions.add(Permission.objects.get(content_type__app_label="nto_travel", codename="view_nto_application"))
        cls.consent = NtoConsentRevision.objects.create(version="review-test", text="Тестовое согласие")
        cls.campaign = cls.make_campaign("review-season")
        cls.profile = NtoProfile.objects.create(campaign=cls.campaign, external_code="robot", name="Робототехника", final_city="Томск")
        cls.campaign.state = "published"
        cls.campaign.save()

    @classmethod
    def make_campaign(cls, slug):
        return NtoCampaign.objects.create(slug=slug, academic_year=slug, name=slug, consent_revision=cls.consent, opens_at=timezone.now()-timedelta(days=1), closes_at=timezone.now()+timedelta(days=10))

    def app(self, **kwargs):
        user = kwargs.pop("user", None)
        if user is None:
            user = get_user_model().objects.create_user(username=f"candidate{get_user_model().objects.count()}")
        return NtoApplication.objects.create(user=user, campaign=kwargs.pop("campaign", self.campaign), status=kwargs.pop("status", "submitted"), **kwargs)

    def data(self, version=0, **kwargs):
        return {"version": version, "criticality": 4, "criticality_reason": "Высокая стоимость поездки", "motivation": 5, "motivation_reason": "Содержательная подготовка", **kwargs}

    def url(self, name, app):
        return reverse("nto_staff:"+name, args=[app.campaign.slug, app.pk])

    def test_totals_season_filters_missing_cost_and_no_duplicate_profiles(self):
        from .models import NtoApplicationProfile
        first = self.app(status="approved", ticket_cost=10000, region="Томск")
        self.app(status="approved", ticket_cost=10000, region="Москва")
        self.app(status="approved", ticket_cost=0)
        self.app(status="approved", ticket_cost=None)
        self.app(status="rejected", ticket_cost=99999)
        self.app(campaign=self.make_campaign("other"), status="approved", ticket_cost=88888)
        second_profile = NtoProfile.objects.create(campaign=self.campaign, external_code="ai", name="ИИ", final_city="Москва")
        for rank, profile in enumerate([self.profile, second_profile], 1):
            NtoApplicationProfile.objects.create(application=first, profile=profile, rank=rank)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("nto_staff:queue"), {"campaign": self.campaign.slug, "region": "Томск"})
        self.assertEqual(response.context["approved_totals"], {"total": Decimal(20000), "count": 4, "missing": 1})
        self.assertEqual(response.context["filtered_totals"], {"total": Decimal(10000), "count": 1, "missing": 0})
        self.assertNotContains(response, "Стоимость одобренных поездок")
        self.assertNotContains(response, "Из них по текущим фильтрам")
        self.assertEqual(list(response.context["applications"]), [first])
        first.ticket_cost = 30000
        first.save()
        response = self.client.get(reverse("nto_staff:queue"), {"campaign": self.campaign.slug, "status": "rejected"})
        self.assertEqual(response.context["approved_totals"]["total"], 40000)
        self.assertEqual(response.context["filtered_totals"]["count"], 0)
        from .services import review_application
        new_app = self.app(ticket_cost=500)
        review_application(new_app.pk, self.staff, "approve")
        response = self.client.get(reverse("nto_staff:queue"), {"campaign": self.campaign.slug})
        self.assertEqual(response.context["approved_totals"]["total"], 40500)
        self.assertEqual(response.context["approved_totals"]["count"], 5)
        empty = self.make_campaign("empty")
        response = self.client.get(reverse("nto_staff:queue"), {"campaign": empty.slug})
        self.assertEqual(response.context["approved_totals"], {"total": 0, "count": 0, "missing": 0})

    def test_sorting_both_directions_nulls_last_ties_and_filter_links(self):
        missing = self.app(ticket_cost=None)
        low = self.app(ticket_cost=0)
        high = self.app(ticket_cost=20000)
        tie = self.app(ticket_cost=20000)
        save_review(low.pk, self.staff, self.data(criticality=1, motivation=2))
        save_review(high.pk, self.staff, self.data(criticality=5, motivation=5))
        save_review(tie.pk, self.staff, self.data(criticality=5, motivation=5))
        for key in ("cost", "criticality", "motivation"):
            for direction, expected in [("asc", [low.pk, tie.pk, high.pk, missing.pk]), ("desc", [tie.pk, high.pk, low.pk, missing.pk])]:
                with self.subTest(key=key, direction=direction):
                    self.assertEqual(list(_filtered(self.campaign, {"sort": key, "direction": direction}).values_list("pk", flat=True)), expected)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("nto_staff:queue"), {"campaign": self.campaign.slug, "status": "submitted", "q": "test", "sort": "cost"})
        self.assertIn("direction=desc", response.context["sort_links"]["cost"])
        self.assertIn("status=submitted", response.context["sort_links"]["criticality"])
        self.assertIn("q=test", response.context["sort_links"]["criticality"])
        self.assertEqual(rubles(None), "Не указана")
        self.assertEqual(rubles(0), "0 ₽")
        self.assertEqual(rubles(20000), "20\u00a0000 ₽")

    def test_review_history_read_marks_and_noop(self):
        app = self.app()
        review = save_review(app.pk, self.staff, self.data())
        self.assertEqual(review.version, 1)
        self.assertEqual(app.read_marks.count(), 1)
        read_at = app.read_marks.get().read_at
        self.assertEqual(app.events.filter(action="review_saved").count(), 1)
        save_review(app.pk, self.staff, self.data(version=1))
        mark_read(app.pk, self.staff)
        self.assertEqual(app.events.filter(action="review_saved").count(), 1)
        self.assertEqual(app.events.filter(action="marked_read").count(), 1)
        self.assertEqual(app.read_marks.get().read_at, read_at)
        updated = save_review(app.pk, self.colleague, self.data(version=1, criticality=3, criticality_reason="Другое обоснование"))
        self.assertEqual(updated.author, self.colleague)
        self.assertEqual(updated.version, 2)
        self.assertEqual(app.read_marks.count(), 2)
        event = app.events.filter(action="review_saved").first()
        self.assertIn("Было: 4\nСтало: 3", event.comment)
        self.assertIn("Высокая стоимость поездки", event.comment)
        self.assertIn("Другое обоснование", event.comment)
        self.assertNotIn("Обоснование мотивации", event.comment)
        app.refresh_from_db()
        self.assertEqual(app.status, "submitted")
        self.assertEqual(Notification.objects.count(), 0)

    def test_stale_versions_cannot_overwrite_create_or_update(self):
        app = self.app()
        save_review(app.pk, self.staff, self.data())
        with self.assertRaises(ReviewConflict):
            save_review(app.pk, self.colleague, self.data())
        save_review(app.pk, self.staff, self.data(version=1, criticality=2))
        with self.assertRaises(ReviewConflict):
            save_review(app.pk, self.colleague, self.data(version=1, criticality=1))
        self.assertEqual(NtoApplicationReview.objects.get(application=app).criticality, 2)
        self.assertFalse(app.read_marks.filter(user=self.colleague).exists())

    def test_validation_permissions_csrf_and_statuses(self):
        app = self.app()
        for changes in ({"criticality": 0}, {"motivation": 6}, {"criticality_reason": " "}, {"motivation_reason": "x"*3001}, {"version": -1}):
            self.assertFalse(ReviewForm(self.data(**changes)).is_valid())
        for user in (self.user, self.viewer):
            with self.assertRaises(PermissionDenied):
                save_review(app.pk, user, self.data())
            self.client.force_login(user)
            for action in ("save_review", "mark_read"):
                self.assertEqual(self.client.post(self.url(action, app), self.data()).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url("save_review", app)).status_code, 405)
        self.assertEqual(self.client.get(self.url("mark_read", app)).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.staff)
        self.assertEqual(csrf.post(self.url("save_review", app), self.data()).status_code, 403)
        self.assertEqual(csrf.post(self.url("mark_read", app)).status_code, 403)
        self.assertEqual(self.client.post(self.url("save_review", app), self.data(motivation_reason="")).status_code, 400)
        self.assertFalse(NtoApplicationReview.objects.exists())
        self.assertFalse(NtoApplicationRead.objects.exists())
        for status in ("submitted", "clarification", "approved", "rejected"):
            current = self.app(status=status)
            self.assertEqual(self.client.post(self.url("save_review", current), self.data()).status_code, 302)
        draft = self.app(status="draft")
        self.assertEqual(self.client.post(self.url("save_review", draft), self.data()).status_code, 400)
        self.assertFalse(NtoApplicationReview.objects.filter(application=draft).exists())

    def test_database_constraints(self):
        app = self.app()
        data = {key: value for key, value in self.data().items() if key != "version"}
        for value in (0, 6):
            for field in ("criticality", "motivation"):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    NtoApplicationReview.objects.create(application=app, **{**data, field: value})
        mark_read(app.pk, self.staff)
        with self.assertRaises(IntegrityError), transaction.atomic():
            NtoApplicationRead.objects.create(application=app, user=self.staff)

    def test_get_is_not_explicit_read_and_conflict_preserves_form(self):
        app = self.app()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url("detail", app)).status_code, 200)
        self.assertFalse(app.read_marks.exists())
        save_review(app.pk, self.colleague, self.data())
        response = self.client.post(self.url("save_review", app), self.data(criticality_reason="Мой несохранённый текст"))
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Мой несохранённый текст", status_code=409)
        self.assertContains(response, "Коллега уже изменил", status_code=409)
        self.client.force_login(self.viewer)
        response = self.client.get(self.url("detail", app))
        self.assertContains(response, "Содержательная подготовка")
        self.assertNotContains(response, "Сохранить заключение")
        self.assertNotContains(response, "Прочитано мной")

    def test_participant_cannot_see_review_and_export_uses_numbers_and_text(self):
        app = self.app(user=self.user)
        save_review(app.pk, self.staff, self.data(criticality_reason="=SECRET()", motivation_reason="<script>private</script>"))
        select_program(self.user, "nto")
        self.client.force_login(self.user)
        for name in ("application", "review"):
            response = self.client.get(reverse("nto_travel:"+name, args=[self.campaign.slug]))
            self.assertNotContains(response, "SECRET")
            self.assertNotContains(response, "private")
        self.staff.groups.add(Group.objects.get(name="Администратор НТО"))
        self.client.force_login(self.staff)
        response = self.client.get(reverse("nto_staff:export", args=[self.campaign.slug]))
        book = load_workbook(BytesIO(response.content))
        for sheet in book:
            cells = dict(zip([cell.value for cell in sheet[1]], sheet[2]))
            self.assertEqual(cells["Критичность поддержки"].value, 4)
            self.assertEqual(cells["Критичность поддержки"].data_type, "n")
            self.assertEqual(cells["Автор заключения"].value, "Анна Иванова")
            self.assertEqual(cells["Прочитали"].value, "Анна Иванова")
        self.assertEqual(cells["Обоснование критичности"].data_type, "s")
        self.assertEqual(cells["Обоснование критичности"].value, "=SECRET()")
        self.assertEqual(cells["Заключение изменено"].data_type, "d")
        detail = self.client.get(self.url("detail", app))
        self.assertNotContains(detail, "<script>private</script>")

    def test_review_survives_resubmission_and_admin_edit(self):
        from .tests import NtoTravelTests
        from .services import submit_application
        app = NtoTravelTests.filled_application(self)
        app.status = "clarification"
        app.clarification_due_at = timezone.now()+timedelta(days=1)
        app.save()
        review = save_review(app.pk, self.staff, self.data())
        submit_application(app.pk, self.user, consent_confirmed=True)
        self.staff.groups.add(Group.objects.get(name="Администратор НТО"))
        self.client.force_login(self.staff)
        response = self.client.get(self.url("edit", app))
        payload = {form.add_prefix(name): form[name].value() for form in response.context["forms"] for name in form.fields if form[name].value() is not None}
        payload.update({"profile_order": f"[{self.profile.pk}]", "personal-first_name": "Изменение"})
        self.assertEqual(self.client.post(self.url("edit", app), payload).status_code, 302)
        review.refresh_from_db()
        self.assertEqual(review.version, 1)
        self.assertEqual(app.read_marks.count(), 1)
