import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from scholar_form.models import UserInfo

from .models import Course, CourseSelection, School, Subject


class CoursePaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="course-reader")
        UserInfo.objects.create(user=cls.user, status="SCHOLAR")
        cls.school = School.objects.create(name="Школа 12")
        cls.subject = Subject.objects.create(name="Математика", slug="math")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("study:schools")

    def make_courses(self, count):
        Course.objects.bulk_create([
            Course(school=self.school, subject=self.subject,
                   title=f"Курс {i:02d}", description="ЕГЭ 12 & + page=2")
            for i in range(count)
        ])

    def links(self, response):
        return [unescape(link) for link in re.findall(
            r'class="page-link" href="([^"]+)"', response.content.decode()
        )]

    def test_first_page_at_pagination_boundary(self):
        for count in (0, 12, 13, 25):
            with self.subTest(count=count):
                Course.objects.all().delete()
                self.make_courses(count)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context["courses"]), min(count, 12))
                self.assertEqual(self.links(response), ["?page=2"] if count > 12 else [])

    def test_navigation_preserves_filters(self):
        self.make_courses(25)
        filters = {"school": str(self.school.pk), "subject": str(self.subject.pk),
                   "q": "ЕГЭ 12 & + page=2"}
        response = self.client.get(self.url, {**filters, "page": "2"})
        links = self.links(response)
        self.assertEqual(len(links), 2)
        for link, page, count in zip(links, ("1", "3"), (12, 1)):
            self.assertEqual(parse_qs(urlsplit(link).query),
                             {**{key: [value] for key, value in filters.items()}, "page": [page]})
            target = self.client.get(self.url + link)
            self.assertEqual(target.status_code, 200)
            self.assertEqual(target.context["courses"].number, int(page))
            self.assertEqual(len(target.context["courses"]), count)

    def test_invalid_page_uses_paginator_fallback(self):
        self.make_courses(25)
        for value, expected in (("", 1), ("abc", 1), ("999", 3), ("0", 3), ("-1", 3)):
            with self.subTest(page=value):
                response = self.client.get(self.url, {"page": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["courses"].number, expected)


class CourseTrackAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Track school")
        cls.subject = Subject.objects.create(name="Track subject", slug="track-subject")
        cls.main_only_course = Course.objects.create(
            school=cls.school,
            subject=cls.subject,
            title="Main only",
        )
        cls.shared_course = Course.objects.create(
            school=cls.school,
            subject=cls.subject,
            title="Shared",
            available_to_alternative=True,
        )

    def make_user(self, username, status=None):
        user = get_user_model().objects.create_user(username=username)
        if status is not None:
            UserInfo.objects.create(user=user, status=status)
        return user

    def test_scholar_can_see_and_select_every_course(self):
        user = self.make_user("scholar", "SCHOLAR")
        self.client.force_login(user)

        response = self.client.get(reverse("study:schools"))
        self.assertContains(response, "Main only")
        self.assertContains(response, "Shared")

        response = self.client.post(
            reverse("study:select_course", args=[self.main_only_course.pk]),
            {"motivation": "Useful"},
        )
        self.assertRedirects(response, reverse("study:schools"))
        self.assertTrue(
            CourseSelection.objects.filter(user=user, course=self.main_only_course).exists()
        )

    def test_alternative_only_sees_and_selects_allowed_courses(self):
        user = self.make_user("alternative", "ALTERNATIVE")
        self.client.force_login(user)

        response = self.client.get(reverse("study:schools"))
        self.assertNotContains(response, "Main only")
        self.assertContains(response, "Shared")

        response = self.client.post(
            reverse("study:select_course", args=[self.shared_course.pk]),
            {"motivation": "Useful"},
        )
        self.assertRedirects(response, reverse("study:schools"))
        self.assertTrue(
            CourseSelection.objects.filter(user=user, course=self.shared_course).exists()
        )

    def test_alternative_cannot_access_or_change_disallowed_course(self):
        user = self.make_user("alternative-hidden", "ALTERNATIVE")
        selection = CourseSelection.objects.create(
            user=user,
            course=self.main_only_course,
            motivation="Existing choice",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("study:schools"))
        self.assertNotContains(response, "Existing choice")

        select_url = reverse("study:select_course", args=[self.main_only_course.pk])
        self.assertEqual(self.client.get(select_url).status_code, 403)
        self.assertEqual(
            self.client.post(select_url, {"motivation": "Changed"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("study:unselect_course", args=[self.main_only_course.pk])
            ).status_code,
            403,
        )
        selection.refresh_from_db()
        self.assertEqual(selection.motivation, "Existing choice")

    def test_other_statuses_and_missing_profile_cannot_access_study(self):
        urls = [
            reverse("study:schools"),
            reverse("study:select_course", args=[self.shared_course.pk]),
            reverse("study:unselect_course", args=[self.shared_course.pk]),
            reverse("study:universities"),
            reverse("study:delete_university_priority", args=[999]),
            reverse("study:assessments"),
        ]
        for status in ("CANDIDATE", "FINAL STAGE", "ALUMNUS", None):
            with self.subTest(status=status):
                user = self.make_user(f"blocked-{status}", status)
                self.client.force_login(user)
                for url in urls:
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_study_navigation_is_only_visible_for_study_tracks(self):
        study_url = reverse("study:schools")
        for status, visible in (
            ("SCHOLAR", True),
            ("ALTERNATIVE", True),
            ("CANDIDATE", False),
            ("FINAL STAGE", False),
            ("ALUMNUS", False),
        ):
            with self.subTest(status=status):
                user = self.make_user(f"navigation-{status}", status)
                sidebar = render_to_string(
                    "core/_sidebar.html",
                    {"user": user, "active": ""},
                )
                self.assertEqual(study_url in sidebar, visible)
