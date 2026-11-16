from django.test import TestCase
from django.urls import reverse
from .models import EmailSubscriber


class SubscriptionConsentTests(TestCase):
    def test_both_consents_are_required(self):
        for flags in ({}, {'personal_data_consent': 'on'}, {'privacy_consent': 'on'}):
            response = self.client.post(reverse('announce'), {'email': 'child@example.test', **flags})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(EmailSubscriber.objects.exists())
        response = self.client.post(reverse('announce'), {'email': 'child@example.test', 'personal_data_consent': 'on', 'privacy_consent': 'on'})
        self.assertRedirects(response, reverse('thanks_subscribe'))
        self.assertTrue(EmailSubscriber.objects.filter(email='child@example.test').exists())
