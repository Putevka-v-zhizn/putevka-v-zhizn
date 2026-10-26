from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import RegistrationPersonalData, UserProgramPreferences
from core.services.programs import select_program
from nto_travel.models import NtoApplication, NtoApplicationProfile, NtoCampaign, NtoConsentRevision, NtoProfile
from scholar_form.models import UserInfo


class ProgramSelectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('programs@example.test', email='programs@example.test', password='ProgramTest2026!')
        self.info = UserInfo.objects.create(user=self.user)
        self.attempt = RegistrationPersonalData.objects.create(user=self.user, email=self.user.email, password=self.user.password, current_step='finish')
        self.preferences = UserProgramPreferences.objects.create(user=self.user)
        self.client.force_login(self.user)

    def campaign(self, slug='season'):
        consent = NtoConsentRevision.objects.create(version=slug, text='Тестовое согласие')
        campaign = NtoCampaign.objects.create(slug=slug, academic_year=slug, name='Сезон НТО', opens_at=timezone.now()-timedelta(days=1), closes_at=timezone.now()+timedelta(days=1), consent_revision=consent)
        profile = NtoProfile.objects.create(campaign=campaign, external_code='robot', name='Роботы', final_city='Томск')
        campaign.state = 'published'
        campaign.save()
        return campaign, profile

    def test_unchosen_account_always_returns_to_choice(self):
        for url in ('index', 'apply', 'finish_registration'):
            self.assertRedirects(self.client.get(reverse(url)), reverse('programs'))
        page = self.client.get(reverse('programs'))
        self.assertContains(page, 'Выберите программу')
        self.assertContains(page, 'Выбрать НТО')
        self.assertNotContains(page, 'id="selectionMenu"')
        self.client.logout()
        self.client.login(username=self.user.username, password='ProgramTest2026!')
        self.assertRedirects(self.client.get(reverse('index')), reverse('programs'))

    def test_connect_both_switch_and_deep_links_without_data_loss(self):
        self.assertRedirects(self.client.post(reverse('program_select'), {'program':'main'}), reverse('apply'))
        self.info.first_name = 'Сохранённое имя'
        self.info.save(update_fields=['first_name'])
        page = self.client.get(reverse('index'))
        self.assertContains(page, 'id="selectionMenu"')
        self.assertNotContains(page, 'id="programSwitcher"')
        self.assertNotContains(page, 'href="' + reverse('nto_travel:landing') + '"')
        self.assertRedirects(self.client.post(reverse('program_select'), {'program':'nto'}), reverse('nto_travel:landing'))
        self.preferences.refresh_from_db()
        self.assertTrue(self.preferences.main_enabled and self.preferences.nto_enabled)
        page = self.client.get(reverse('index'))
        self.assertContains(page, 'id="programSwitcher"')
        self.assertNotContains(page, 'id="selectionMenu"')
        self.assertNotContains(page, 'id="selectionDropdown"')
        campaign, profile = self.campaign()
        application = NtoApplication.objects.create(user=self.user, campaign=campaign, first_name='Ответ НТО')
        NtoApplicationProfile.objects.create(application=application, profile=profile, rank=1)
        self.client.post(reverse('program_select'), {'program':'main'})
        page = self.client.get(reverse('nto_travel:application', args=[campaign.slug]))
        self.assertContains(page, 'Ответ НТО')
        self.assertNotContains(page, 'id="selectionMenu"')
        self.preferences.refresh_from_db()
        self.assertEqual(self.preferences.active_program, 'main')
        self.info.refresh_from_db()
        self.assertEqual(self.info.first_name, 'Сохранённое имя')
        page = self.client.get(reverse('index'))
        self.assertContains(page, 'id="selectionMenu"')

    def test_nto_only_has_no_main_flow_and_unconnected_routes_require_choice(self):
        self.client.post(reverse('program_select'), {'program':'nto'})
        page = self.client.get(reverse('index'))
        self.assertContains(page, 'Открыть НТО')
        self.assertNotContains(page, 'id="selectionMenu"')
        self.assertNotContains(page, 'id="programSwitcher"')
        self.assertRedirects(self.client.get(reverse('apply')), reverse('programs'))

    def test_remembered_campaign_and_closed_campaign_fallback(self):
        campaign, _ = self.campaign()
        self.attempt.nto_campaign_slug = campaign.slug
        self.attempt.save()
        self.assertRedirects(self.client.post(reverse('program_select'), {'program':'nto'}), reverse('nto_travel:apply_step', args=[campaign.slug,'personal']))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.nto_campaign_slug, '')
        campaign.closes_at = timezone.now()-timedelta(seconds=1)
        campaign.save()
        self.attempt.nto_campaign_slug = campaign.slug
        self.attempt.save()
        response = self.client.post(reverse('program_select'), {'program':'nto'}, follow=True)
        self.assertContains(response, 'Приём заявок сейчас закрыт')

    def test_post_validation_csrf_and_registration_gate(self):
        self.assertEqual(self.client.get(reverse('program_select')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('program_select'), {'program':'bogus'}), reverse('programs'))
        self.preferences.refresh_from_db()
        self.assertEqual(self.preferences.active_program, '')
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse('program_select'), {'program':'main'}).status_code, 403)
        self.attempt.current_step = 'email_verification'
        self.attempt.save()
        self.assertRedirects(self.client.get(reverse('programs')), reverse('redirect_to_current_step'), fetch_redirect_response=False)

    def test_staff_bypasses_choice(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.assertRedirects(self.client.get(reverse('programs')), reverse('index'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('index')), '/staff/users', fetch_redirect_response=False)

    @patch('core.views.send_email_verification_code')
    def test_plain_registration_creates_empty_preferences(self, send_email):
        self.client.logout()
        self.client.post(reverse('register_initial'), {'email':'new-program@example.test', 'password':'ProgramTest2026!', 'password_confirm':'ProgramTest2026!'})
        user = get_user_model().objects.get(email='new-program@example.test')
        self.assertEqual(user.program_preferences.active_program, '')
        self.assertFalse(user.program_preferences.main_enabled or user.program_preferences.nto_enabled)


class ProgramMigrationTests(TestCase):
    def test_existing_memberships_are_migrated(self):
        users = [get_user_model().objects.create_user(f'migrate-{i}@example.test') for i in range(4)]
        for i, user in enumerate(users):
            UserInfo.objects.create(user=user, form_status='submitted' if i==2 else 'draft')
        for i in (1,2):
            RegistrationPersonalData.objects.create(user=users[i], email=f'migrate-{i}@example.test', nto_campaign_slug='old-season')
        consent = NtoConsentRevision.objects.create(version='migration', text='Test')
        campaign = NtoCampaign.objects.create(slug='migration', academic_year='migration', name='Migration', opens_at=timezone.now(), closes_at=timezone.now()+timedelta(days=1), consent_revision=consent)
        NtoApplication.objects.create(user=users[3], campaign=campaign)
        migrate = import_module('core.migrations.0007_migrate_program_preferences').migrate_preferences
        migrate(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        actual = list(UserProgramPreferences.objects.order_by('user_id').values_list('main_enabled','nto_enabled','active_program'))
        self.assertEqual(actual, [(True,False,'main'), (False,True,'nto'), (True,True,'nto'), (False,True,'nto')])
