from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase

from core.models import RegistrationPersonalData, UserProgramPreferences
from nto_travel.models import NtoApplication
from scholar_form.models import UserInfo
from deploy.qa.create_test_users import create_accounts


class QaTestAccountsTests(TestCase):
    def record(self, name="one", program="nto"):
        return {"username": f"qa.{name}@example.invalid", "program": program, "password_hash": make_password("test-password")}

    @patch("deploy.qa.create_test_users.BASE_URL", "https://qa.putevka-v-zhizn.dmitrylem.ru")
    def test_empty_accounts_ready_for_login(self):
        records = [self.record(mode, mode) for mode in ("nto", "main", "both", "choose")]
        create_accounts(records)
        for record in records:
            user = get_user_model().objects.get(username=record["username"])
            self.assertTrue(user.check_password("test-password"))
            self.assertFalse(user.is_staff)
            self.assertEqual(RegistrationPersonalData.objects.get(user=user).current_step, "finish")
            self.assertEqual(UserInfo.objects.get(user=user).form_status, "draft")
            self.assertFalse(NtoApplication.objects.filter(user=user).exists())
            preferences = UserProgramPreferences.objects.get(user=user)
            self.assertEqual(preferences.main_enabled, record["program"] in ("main", "both"))
            self.assertEqual(preferences.nto_enabled, record["program"] in ("nto", "both"))

    @patch("deploy.qa.create_test_users.BASE_URL", "https://example.org")
    def test_other_sites_are_rejected(self):
        with self.assertRaises(RuntimeError):
            create_accounts([self.record()])
        self.assertFalse(get_user_model().objects.exists())

    @patch("deploy.qa.create_test_users.BASE_URL", "https://qa.putevka-v-zhizn.dmitrylem.ru")
    def test_existing_accounts_are_not_overwritten_and_batch_is_atomic(self):
        existing = self.record("existing")
        create_accounts([existing])
        with self.assertRaises(ValueError):
            create_accounts([self.record("new"), existing])
        self.assertFalse(get_user_model().objects.filter(username="qa.new@example.invalid").exists())
        self.assertEqual(get_user_model().objects.count(), 1)
