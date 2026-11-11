from urllib.parse import parse_qs, urlsplit
from html import unescape
import re

from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from scholar_form.models import UserInfo
from .admin import PreparationDirectionAdminForm
from .models import Course, CourseDuration, CourseSelection, PreparationDirection, School, Subject
from .preparation import ensure_course_direction, preparation_rows


class CourseOptionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username="course-options")
        UserInfo.objects.create(user=cls.user, status="SCHOLAR")
        cls.staff = User.objects.create_superuser(username="options-admin", password="test")
        cls.subject = Subject.objects.create(name="Математика", slug="options-math")
        cls.school = School.objects.create(name="Школа опций")
        cls.duration = CourseDuration.objects.create(name="Полугодовой")
        cls.course = Course.objects.create(title="Курс ЕГЭ", school=cls.school, subject=cls.subject, duration=cls.duration)
        cls.olymp_subject = Subject.objects.create(name="Олимпиадная математика", slug="olympiad-math", is_olympiad=True)
        cls.olymp = Course.objects.create(title="Олимпиадный курс", school=cls.school, subject=cls.olymp_subject)

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("study:schools")

    def select(self, course=None):
        return self.client.post(reverse("study:select_course", args=[(course or self.course).pk]), {"motivation": "Подготовка"})

    def test_courses_automatically_supply_status_and_clear_not_started(self):
        direction = PreparationDirection.objects.create(user=self.user, subject=self.subject, not_started=True)
        self.select()
        direction.refresh_from_db()
        self.assertFalse(direction.not_started)
        response = self.client.get(self.url)
        row = response.context["directions"][0]
        self.assertEqual(row.display_methods, ["Готовлюсь на курсах"])
        self.assertFalse(row.editing)
        self.assertContains(response, "Готовлюсь на курсах")
        self.assertNotContains(response, "Способ подготовки не указан")
        self.assertTrue(row.methods_form.fields["not_started"].widget.is_hidden)

    def test_course_and_manual_methods_survive_removal(self):
        direction = PreparationDirection.objects.create(user=self.user, subject=self.subject, independently=True, with_tutor_or_school=True)
        self.select()
        self.assertEqual(len(preparation_rows(self.user)[0]["child_methods"]), 3)
        self.client.post(reverse("study:unselect_course", args=[self.course.pk]))
        direction.refresh_from_db()
        self.assertTrue(direction.independently and direction.with_tutor_or_school)
        self.assertEqual(len(preparation_rows(self.user)[0]["child_methods"]), 2)

    def test_last_course_removal_returns_to_unanswered(self):
        self.select()
        self.client.post(reverse("study:unselect_course", args=[self.course.pk]))
        self.assertContains(self.client.get(self.url), "Способ подготовки не указан")
        self.assertTrue(self.client.get(self.url).context["directions"][0].editing)

    def test_invalid_answer_keeps_bound_form_open(self):
        self.select()
        direction = PreparationDirection.objects.get(user=self.user)
        response = self.client.post(reverse("study:update_preparation", args=[direction.pk]), {
            f"preparation-{direction.pk}-not_started": "on",
            f"preparation-{direction.pk}-independently": "on",
        })
        self.assertEqual(response.status_code, 200)
        row = response.context["directions"][0]
        self.assertTrue(row.editing)
        self.assertTrue(row.methods_form.is_bound)
        self.assertTrue(row.methods_form.errors)
        self.assertTrue(row.methods_form["independently"].value())
        direction.refresh_from_db()
        self.assertFalse(direction.independently or direction.not_started)

    def test_existing_manual_answer_read_mode_and_explicit_edit(self):
        direction = PreparationDirection.objects.create(user=self.user, subject=self.subject, independently=True)
        self.assertFalse(self.client.get(self.url).context["directions"][0].editing)
        self.assertTrue(self.client.get(self.url, {"edit_preparation": direction.pk}).context["directions"][0].editing)
        response = self.client.post(reverse("study:update_preparation", args=[direction.pk]), {f"preparation-{direction.pk}-with_tutor_or_school": "on"}, follow=True)
        self.assertFalse(response.context["directions"][0].editing)
        self.assertEqual(response.context["directions"][0].display_methods, ["Готовлюсь с репетитором / в школе"])

    def test_olympiad_assignment_hidden_preserved_and_does_not_block_delete(self):
        CourseSelection.objects.create(user=self.user, course=self.olymp)
        direction = PreparationDirection.objects.create(user=self.user, subject=self.subject, independently=True)
        response = self.client.get(self.url)
        self.assertNotContains(response, self.olymp.title)
        self.assertFalse(response.context["directions"][0].has_courses)
        self.assertEqual(self.select(self.olymp).status_code, 404)
        self.assertIsNone(ensure_course_direction(self.user, self.olymp))
        self.client.post(reverse("study:delete_preparation", args=[direction.pk]))
        self.assertFalse(PreparationDirection.objects.filter(pk=direction.pk).exists())
        self.assertEqual(CourseSelection.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.client.get(self.url).context["directions"], [])

    def test_staff_summary_uses_same_status_and_filters_olympiads(self):
        CourseSelection.objects.create(user=self.user, course=self.course)
        CourseSelection.objects.create(user=self.user, course=self.olymp)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("staff_study_detail", args=[self.user.pk]))
        self.assertContains(response, "Готовится на курсах")
        self.assertContains(response, self.duration.name)
        self.assertNotContains(response, "Способ подготовки не указан")
        self.assertNotContains(response, self.olymp.title)

    def test_admin_assignment_normalizes_answer_and_validates_methods(self):
        direction = PreparationDirection.objects.create(user=self.user, subject=self.subject, not_started=True)
        self.client.force_login(self.staff)
        response = self.client.post(reverse("admin:my_study_courseselection_add"), {
            "user": self.user.pk, "course": self.course.pk, "motivation": "Назначен", "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        direction.refresh_from_db()
        self.assertFalse(direction.not_started)
        form = PreparationDirectionAdminForm(data={"user": self.user.pk, "subject": self.subject.pk, "not_started": True}, instance=direction)
        self.assertFalse(form.is_valid())

    def test_duration_filters_preserve_pagination_and_optional_value(self):
        for i in range(13):
            Course.objects.create(title=f"Практика {i}", school=self.school, subject=self.subject, duration=self.duration)
        Course.objects.create(title="Без срока", school=self.school, subject=self.subject)
        filters = {"duration": str(self.duration.pk), "subject": str(self.subject.pk), "school": str(self.school.pk), "q": "Практика"}
        response = self.client.get(self.url, filters)
        self.assertEqual(response.context["courses"].paginator.count, 13)
        self.assertNotContains(response, "Без срока")
        links = re.findall(r'class="page-link" href="([^"]+)"', response.content.decode())
        self.assertTrue(links)
        self.assertEqual(parse_qs(urlsplit(unescape(links[0])).query), {**{key:[value] for key,value in filters.items()}, "page":["2"]})
        self.assertContains(self.client.get(reverse("study:select_course", args=[self.course.pk])), self.duration.name)
        with self.assertRaises(ProtectedError):
            self.duration.delete()

    def test_admin_duration_and_olympiad_filters(self):
        self.client.force_login(self.staff)
        url = reverse("admin:my_study_course_changelist")
        response = self.client.get(url, {"duration__id__exact": self.duration.pk})
        self.assertEqual(response.context["cl"].result_count, 1)
        response = self.client.get(url, {"subject__is_olympiad__exact": "1"})
        self.assertEqual(response.context["cl"].result_count, 1)
        self.assertEqual(response.context["cl"].result_list[0].pk, self.olymp.pk)

    def test_all_courses_follow_subject_classification(self):
        second = Course.objects.create(title="Второй олимпиадный курс", school=self.school, subject=self.olymp_subject)
        CourseSelection.objects.create(user=self.user, course=self.olymp)
        CourseSelection.objects.create(user=self.user, course=second)
        hidden_direction = PreparationDirection.objects.create(user=self.user, subject=self.olymp_subject, independently=True)
        from .forms import PreparationAddForm, CourseFilterForm
        self.assertFalse(PreparationAddForm({"direction": str(self.olymp_subject.pk)}).is_valid())
        self.assertFalse(CourseFilterForm({"subject": self.olymp_subject.pk}).is_valid())
        response = self.client.get(self.url)
        self.assertNotContains(response, self.olymp_subject.name)
        self.assertNotContains(response, second.title)
        self.assertEqual(response.context["directions"], [])
        for action in ("update_preparation", "delete_preparation"):
            self.assertEqual(self.client.post(reverse(f"study:{action}", args=[hidden_direction.pk])).status_code, 404)
        self.olymp_subject.is_olympiad = False
        self.olymp_subject.save()
        response = self.client.get(self.url)
        self.assertContains(response, second.title)
        self.assertTrue(response.context["directions"][0].has_courses)
        self.assertEqual(len(response.context["directions"][0].selections), 2)

    def test_subject_admin_flag_and_course_form_without_individual_flag(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin:my_study_subject_changelist"), {"is_olympiad__exact": "1"})
        self.assertEqual(response.context["cl"].result_count, 1)
        response = self.client.get(reverse("admin:my_study_course_change", args=[self.olymp.pk]))
        self.assertNotIn("is_olympiad", response.context["adminform"].form.fields)
        response = self.client.get(reverse("admin:my_study_preparationdirection_add"))
        self.assertNotIn(self.olymp_subject, response.context["adminform"].form.fields["subject"].queryset)
