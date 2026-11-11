from unittest import skipIf

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


@skipIf(settings.MIGRATION_MODULES.get("my_study", "enabled") is None,
        "The full legacy suite disables application migrations; run this test separately.")
class OlympiadSubjectMigrationTests(TransactionTestCase):
    old = ("my_study", "0007_courseduration_course_is_olympiad_course_duration")
    new = ("my_study", "0009_remove_course_olympiad_flag")

    def test_mixed_subject_preserves_assignments_and_ordinary_courses(self):
        executor = MigrationExecutor(connection)
        self.addCleanup(lambda: MigrationExecutor(connection).migrate([self.new]))
        executor.migrate([self.old])
        apps = executor.loader.project_state([self.old]).apps
        Subject = apps.get_model("my_study", "Subject")
        Course = apps.get_model("my_study", "Course")
        School = apps.get_model("my_study", "School")
        Selection = apps.get_model("my_study", "CourseSelection")
        user = apps.get_model(settings.AUTH_USER_MODEL).objects.create(username="migration-child")
        subject = Subject.objects.create(name="Биология", slug="biology")
        # An existing name/slug must not be repurposed or overwritten.
        collision = Subject.objects.create(name="Олимпиадная подготовка — Биология", slug=f"olympiad-{subject.pk}")
        school = School.objects.create(name="Школа миграции")
        ordinary = Course.objects.create(title="ЕГЭ", subject=subject, school=school)
        olymp = Course.objects.create(title="Олимпиады", subject=subject, school=school, is_olympiad=True)
        second = Course.objects.create(title="Олимпиады 2", subject=subject, school=school, is_olympiad=True)
        assignment = Selection.objects.create(user=user, course=olymp, motivation="Подготовка")
        executor = MigrationExecutor(connection)
        executor.migrate([self.new])
        apps = executor.loader.project_state([self.new]).apps
        Course = apps.get_model("my_study", "Course")
        Subject = apps.get_model("my_study", "Subject")
        moved = Course.objects.select_related("subject").get(pk=olymp.pk)
        self.assertTrue(moved.subject.is_olympiad)
        self.assertNotEqual(moved.subject_id, subject.pk)
        self.assertNotEqual(moved.subject_id, collision.pk)
        self.assertEqual(Course.objects.get(pk=second.pk).subject_id, moved.subject_id)
        self.assertEqual(Course.objects.get(pk=ordinary.pk).subject_id, subject.pk)
        self.assertFalse(Subject.objects.get(pk=subject.pk).is_olympiad)
        self.assertFalse(Subject.objects.get(pk=collision.pk).is_olympiad)
        self.assertEqual(apps.get_model("my_study", "CourseSelection").objects.get(pk=assignment.pk).course_id, olymp.pk)
        # Rolling back restores course flags without losing assignments.
        executor = MigrationExecutor(connection)
        executor.migrate([self.old])
        apps = executor.loader.project_state([self.old]).apps
        Course = apps.get_model("my_study", "Course")
        self.assertTrue(Course.objects.get(pk=olymp.pk).is_olympiad)
        self.assertFalse(Course.objects.get(pk=ordinary.pk).is_olympiad)
