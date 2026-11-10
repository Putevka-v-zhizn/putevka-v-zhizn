from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from scholar_form.models import UserInfo
from .models import Course, CourseSelection, PreparationDirection, School, Subject


class PreparationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="preparation")
        UserInfo.objects.create(user=cls.user, status="SCHOLAR")
        cls.subject = Subject.objects.create(name="Математика", slug="math")
        cls.school = School.objects.create(name="Школа")
        cls.course = Course.objects.create(title="ЕГЭ", school=cls.school, subject=cls.subject)
        cls.olymp = Course.objects.create(title="Олимпиадный курс", school=cls.school, subject=cls.subject, is_olympiad=True)

    def setUp(self):
        self.client.force_login(self.user)

    def direction(self):
        return PreparationDirection.objects.get_or_create(user=self.user, subject=self.subject)[0]

    def save_methods(self, direction, **methods):
        return self.client.post(reverse("study:update_preparation", args=[direction.pk]),
            {f"preparation-{direction.pk}-{key}": "on" for key, value in methods.items() if value})

    def select(self, course):
        return self.client.post(reverse("study:select_course", args=[course.pk]), {"motivation": "Подготовка"})

    def test_add_directions_idempotently_and_delete(self):
        for value in (str(self.subject.pk), "olympiad"):
            for _ in range(2):
                self.client.post(reverse("study:add_preparation"), {"direction": value})
        self.assertEqual(PreparationDirection.objects.count(), 2)
        for direction in PreparationDirection.objects.all():
            self.client.post(reverse("study:delete_preparation", args=[direction.pk]))
        self.assertFalse(PreparationDirection.objects.exists())
        self.client.post(reverse("study:add_preparation"), {"direction": "invalid"})
        self.assertFalse(PreparationDirection.objects.exists())

    def test_methods_combination_exclusivity_and_unanswered(self):
        direction = self.direction()
        self.assertContains(self.client.get(reverse("study:schools")), "Способ подготовки не указан")
        self.save_methods(direction, independently=True, with_tutor_or_school=True)
        direction.refresh_from_db()
        self.assertTrue(direction.independently and direction.with_tutor_or_school)
        previous_updated = direction.updated_at
        self.save_methods(direction, not_started=True, independently=True)
        direction.refresh_from_db()
        self.assertEqual(direction.updated_at, previous_updated)
        self.save_methods(direction, not_started=True)
        direction.refresh_from_db()
        self.assertTrue(direction.not_started)
        self.assertFalse(direction.independently or direction.with_tutor_or_school)
        self.save_methods(direction)
        direction.refresh_from_db()
        self.assertFalse(direction.has_answer)

    def test_courses_grouped_and_methods_independent(self):
        direction = self.direction()
        self.save_methods(direction, independently=True)
        self.select(self.course)
        another = Course.objects.create(title="Второй курс", school=self.school, subject=self.subject)
        self.select(another)
        self.select(self.olymp)
        response = self.client.get(reverse("study:schools"))
        rows = list(response.context["directions"])
        self.assertEqual([len(row.selections) for row in rows], [2, 1])
        self.client.post(reverse("study:delete_preparation", args=[direction.pk]))
        self.assertTrue(PreparationDirection.objects.filter(pk=direction.pk).exists())
        self.client.post(reverse("study:unselect_course", args=[self.course.pk]))
        direction.refresh_from_db()
        self.assertTrue(direction.independently)
        self.assertEqual(CourseSelection.objects.count(), 2)

    def test_legacy_selections_backfilled_without_changing_answers(self):
        CourseSelection.objects.create(user=self.user, course=self.course)
        CourseSelection.objects.create(user=self.user, course=self.olymp)
        for _ in range(2):
            self.client.get(reverse("study:schools"))
        self.assertEqual(PreparationDirection.objects.count(), 2)
        self.assertEqual(CourseSelection.objects.count(), 2)
        self.assertTrue(all(not row.has_answer for row in PreparationDirection.objects.all()))

    def test_owner_post_only_and_csrf(self):
        direction = self.direction()
        other = get_user_model().objects.create_user(username="other")
        UserInfo.objects.create(user=other, status="SCHOLAR")
        self.client.force_login(other)
        for action in ("update_preparation", "delete_preparation"):
            url = reverse(f"study:{action}", args=[direction.pk])
            self.assertEqual(self.client.post(url).status_code, 404)
            self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.get(reverse("study:add_preparation")).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse("study:add_preparation"), {"direction": "olympiad"}).status_code, 403)

    def test_track_access_and_hidden_courses_still_prevent_deletion(self):
        direction = self.direction()
        CourseSelection.objects.create(user=self.user, course=self.course)
        info = self.user.user_info
        info.status = "ALTERNATIVE"
        info.save()
        response = self.client.get(reverse("study:schools"))
        row = response.context["directions"][0]
        self.assertEqual(row.selections, [])
        self.assertTrue(row.has_courses)
        self.client.post(reverse("study:delete_preparation", args=[direction.pk]))
        self.assertTrue(PreparationDirection.objects.filter(pk=direction.pk).exists())
        for status, expected in (("FINAL STAGE", 302), ("SCHOLAR", 302), ("REJECTED", 403)):
            info.status = status
            info.save()
            self.assertEqual(self.client.post(reverse("study:add_preparation"), {"direction": "olympiad"}).status_code, expected)

    def test_database_constraints(self):
        direction = self.direction()
        invalid = [
            dict(user=self.user, subject=self.subject),
            dict(user=self.user),
            dict(user=self.user, subject=self.subject, is_olympiad=True),
        ]
        for values in invalid:
            with self.assertRaises(IntegrityError), transaction.atomic():
                PreparationDirection.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PreparationDirection.objects.filter(pk=direction.pk).update(not_started=True, independently=True)
