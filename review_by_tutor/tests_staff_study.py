from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from my_study.models import Course, CourseSelection, PreparationDirection, School, Subject
from scholar_form.models import UserInfo


class StaffStudyPreparationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user(username="study-staff", is_staff=True)
        cls.child = User.objects.create_user(username="study-child")
        cls.other = User.objects.create_user(username="study-other")
        UserInfo.objects.create(user=cls.child, status="ALTERNATIVE")
        cls.math = Subject.objects.create(name="Математика", slug="math-staff")
        cls.physics = Subject.objects.create(name="Физика", slug="physics-staff")
        cls.school = School.objects.create(name="Школа подготовки")

    def setUp(self):
        self.client.force_login(self.staff)
        self.url = reverse("staff_study_detail", args=[self.child.pk])

    def test_independent_preparation_without_courses_and_child_isolation(self):
        PreparationDirection.objects.create(user=self.child, subject=self.math, independently=True, with_tutor_or_school=True)
        PreparationDirection.objects.create(user=self.other, subject=self.physics, not_started=True)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Готовится самостоятельно")
        self.assertContains(response, "Готовится с репетитором / в школе")
        self.assertContains(response, "Нет выбранных курсов")
        self.assertContains(response, "Обновлено:")
        self.assertEqual(len(response.context["preparation_rows"]), 1)
        self.assertNotContains(response, self.physics.name)

    def test_legacy_courses_grouped_without_creating_answers_or_hiding_track_courses(self):
        for title in ("Первый курс", "Второй курс"):
            course = Course.objects.create(title=title, school=self.school, subject=self.math)
            CourseSelection.objects.create(user=self.child, course=course)
        response = self.client.get(self.url)
        rows = response.context["preparation_rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["selections"]), 2)
        self.assertContains(response, "Способ подготовки не указан")
        self.assertContains(response, self.school.name)
        self.assertFalse(PreparationDirection.objects.exists())

    def test_not_started_differs_from_unanswered(self):
        PreparationDirection.objects.create(user=self.child, subject=self.math, not_started=True)
        PreparationDirection.objects.create(user=self.child, subject=self.physics)
        response = self.client.get(self.url)
        self.assertContains(response, "Не начал готовиться к этому предмету")
        self.assertContains(response, "Способ подготовки не указан")
        self.assertEqual(len(response.context["preparation_rows"]), 2)

    def test_empty_state_and_access(self):
        self.assertContains(self.client.get(self.url), "Предметы подготовки к ЕГЭ пока не указаны.")
        self.client.force_login(self.child)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_unknown_child_returns_404(self):
        self.assertEqual(self.client.get(reverse("staff_study_detail", args=[999999])).status_code, 404)
