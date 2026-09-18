from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from review_by_tutor.forms import UserPersonalDataStaffForm

from .models import UserInfo, UserPersonalData


class PersonalInfoCompletionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="personal-info-user")
        UserInfo.objects.create(user=self.user, status="SCHOLAR")
        self.client.force_login(self.user)
        self.url = reverse("personal_info")

    def test_user_form_is_hidden_after_first_successful_save(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Основные данные")

        response = self.client.post(
            self.url,
            {"form_type": "personal_data", "first_name": "Иван"},
        )
        self.assertRedirects(response, self.url)

        personal_data = UserPersonalData.objects.get(user=self.user)
        self.assertEqual(personal_data.first_name, "Иван")
        self.assertIsNotNone(personal_data.submitted_by_user_at)
        self.assertNotContains(self.client.get(self.url), "Основные данные")

        self.client.post(
            self.url,
            {"form_type": "personal_data", "first_name": "Изменено"},
        )
        personal_data.refresh_from_db()
        self.assertEqual(personal_data.first_name, "Иван")

    def test_staff_form_can_edit_completed_personal_data(self):
        personal_data = UserPersonalData.objects.get(user=self.user)
        personal_data.first_name = "Иван"
        personal_data.submitted_by_user_at = timezone.now()
        personal_data.save()

        form = UserPersonalDataStaffForm(
            {"first_name": "Пётр", "email": "staff-edited@example.com"},
            instance=personal_data,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        personal_data.refresh_from_db()
        self.assertEqual(personal_data.first_name, "Пётр")
        self.assertEqual(personal_data.email, "staff-edited@example.com")
