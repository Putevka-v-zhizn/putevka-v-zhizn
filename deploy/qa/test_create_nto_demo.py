from unittest.mock import patch

from django.test import TestCase

from nto_travel.models import NtoCampaign, NtoApplication
from deploy.qa.create_nto_demo import create_demo


class QaNtoDemoTests(TestCase):
    @patch("deploy.qa.create_nto_demo.BASE_URL", "https://qa.putevka-v-zhizn.dmitrylem.ru")
    def test_open_campaign_and_profiles_without_answers(self):
        campaign = create_demo()
        self.assertTrue(campaign.accepting)
        self.assertEqual(campaign.profiles.filter(is_active=True).count(), 5)
        self.assertTrue(all(campaign.profiles.values_list("final_city", flat=True)))
        self.assertIsNotNone(campaign.consent_revision)
        self.assertFalse(NtoApplication.objects.exists())
        self.assertEqual(create_demo().pk, campaign.pk)
        self.assertEqual(NtoCampaign.objects.count(), 1)

    @patch("deploy.qa.create_nto_demo.BASE_URL", "https://example.org")
    def test_only_qa_is_allowed(self):
        with self.assertRaises(RuntimeError):
            create_demo()
        self.assertFalse(NtoCampaign.objects.exists())
