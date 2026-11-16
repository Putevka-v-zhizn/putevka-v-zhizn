import copy
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.apps import apps
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import AiTask, MotivationLetter, TelegramMessageTask
from development_mcp.bundle import BundleError
from development_mcp.local_import import ImportCaseError, ensure_local, import_bundle
from development_mcp.tests.sample_bundle import sample_bundle
from development_mcp.schema import TABLES, PROGRAMS
from family_income.models import FamilyIncomeCase, FamilyIncomeDecision, IncomeEvidence
if apps.is_installed('nto_travel'):
    from nto_travel.models import NtoApplication, NtoApplicationProfile, NtoApplicationReview
    from core.models import UserProgramPreferences
from review_by_tutor.models import Interview, InterviewResult
from scholar_form.models import UserInfo


@override_settings(DEBUG=True, DEVELOPMENT_MCP_IMPORT_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DevelopmentCaseImportTests(TestCase):
    def test_real_export_collector_round_trip_for_each_direction(self):
        from development_mcp.tests.test_bundle import exported_case
        for program in PROGRAMS:
            with self.subTest(program=program):
                bundle, _ = exported_case(program)
                result = import_bundle(bundle)
                self.assertEqual(result['records'], len(bundle['records']))
                self.assertTrue(get_user_model().objects.filter(pk=result['user_id']).exists())

    def test_registry_uses_only_live_django_columns(self):
        models = {m._meta.db_table: m for m in apps.get_models()}
        for table, spec in TABLES.items():
            with self.subTest(table=table):
                self.assertTrue(set(spec.columns) <= {field.column for field in models[table]._meta.concrete_fields})

    def test_main_case_preserves_content_relations_and_opens_pages(self):
        bundle = sample_bundle('main')
        with patch('django.db.models.signals.post_save.send') as post, patch('django.db.models.signals.pre_save.send') as pre:
            result = import_bundle(bundle, password='local-test-password')
        post.assert_not_called()
        pre.assert_not_called()
        user = get_user_model().objects.get(pk=result['user_id'])
        self.assertTrue(user.check_password('local-test-password'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        letter = MotivationLetter.objects.get(user=user)
        self.assertEqual(letter.status, 'revision')
        self.assertEqual(letter.admin_score, 4)
        self.assertEqual(letter.letter_text, bundle['records'][1]['fields']['letter_text'])
        interview = Interview.objects.get(user=user)
        self.assertEqual(InterviewResult.objects.get(interview=interview).interviewer_score, 5)
        self.assertEqual(user.staff_notes.count(), 1)
        self.assertEqual(user.test_assignments.count(), 1)
        self.assertEqual(AiTask.objects.count(), 0)
        self.assertEqual(TelegramMessageTask.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.client.force_login(user)
        for url in result['urls']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, follow=True).status_code, 200)
        staff = get_user_model().objects.create_user('local-reviewer', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(result['staff_url']).status_code, 200)

    @skipUnless(apps.is_installed('nto_travel'), 'NTO is not installed in this application')
    def test_nto_case_creates_local_campaign_and_profiles(self):
        result = import_bundle(sample_bundle('nto'))
        user = get_user_model().objects.get(pk=result['user_id'])
        self.assertFalse(user.has_usable_password())
        app = NtoApplication.objects.get(user=user)
        self.assertEqual(app.status, 'approved')
        self.assertEqual(str(app.ticket_cost), '15000.00')
        self.assertEqual(app.achievements, ['Проект'])
        self.assertEqual(NtoApplicationReview.objects.get(application=app).criticality, 4)
        ranked = NtoApplicationProfile.objects.get(application=app)
        self.assertEqual(ranked.profile.campaign_id, app.campaign_id)
        self.assertEqual(ranked.name_snapshot, 'Робототехника')
        self.assertTrue(UserProgramPreferences.objects.get(user=user).nto_enabled)
        self.client.force_login(user)
        for url in result['urls']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_family_case_preserves_amounts_and_uses_empty_file_placeholders(self):
        result = import_bundle(sample_bundle('family_income'))
        user = get_user_model().objects.get(pk=result['user_id'])
        case = FamilyIncomeCase.objects.get(user_info__user=user)
        self.assertEqual(case.family_members_count, 3)
        item = case.family_income_documents.get()
        self.assertFalse(item.document.file)
        self.assertEqual(item.document.user_id, user.pk)
        self.assertEqual(str(IncomeEvidence.objects.get(family_income_document=item).gross_amount), '123456.00')
        self.assertEqual(FamilyIncomeDecision.objects.get(case=case).year.year, 2025)
        self.client.force_login(user)
        for url in result['urls']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_repeated_import_does_not_overwrite_existing_data(self):
        bundle = sample_bundle('main')
        first = import_bundle(bundle)
        letter = MotivationLetter.objects.get(user_id=first['user_id'])
        letter.letter_text = 'Локальные изменения'
        MotivationLetter.objects.filter(pk=letter.pk).update(letter_text=letter.letter_text)
        with self.assertRaises(ImportCaseError):
            import_bundle(bundle)
        letter.refresh_from_db()
        self.assertEqual(letter.letter_text, 'Локальные изменения')
        second = import_bundle(bundle, suffix='copy')
        self.assertNotEqual(first['user_id'], second['user_id'])

    def test_failure_rolls_back_user_and_all_records(self):
        bundle = sample_bundle('main')
        record = next(r for r in bundle['records'] if r['table'] == 'review_by_tutor_interviewresult')
        record['fields']['interviewer_score'] = 'not-a-number'
        with self.assertRaises(Exception):
            import_bundle(bundle)
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertEqual(MotivationLetter.objects.count(), 0)
        self.assertEqual(UserInfo.objects.count(), 0)

    def test_rejects_private_fields_broken_links_and_disabled_import(self):
        original = sample_bundle('main')
        bundle = copy.deepcopy(original)
        bundle['records'][0]['fields']['is_superuser'] = True
        with self.assertRaises(BundleError):
            import_bundle(bundle)
        bundle = copy.deepcopy(original)
        bundle['records'][0]['links']['participant'] = 'invalid-identifier'
        with self.assertRaises(BundleError):
            import_bundle(bundle)
        for flags in ({'DEBUG': False}, {'DEVELOPMENT_MCP_IMPORT_ENABLED': False}):
            with override_settings(**flags), self.assertRaises(ImportCaseError):
                import_bundle(original)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_remote_or_production_database_is_rejected(self):
        fake = type('Connection', (), {'vendor': 'postgresql', 'settings_dict': {'HOST': 'production.example.org', 'NAME': 'putevka'}})()
        with patch('development_mcp.local_import.connections', {'default': fake}), self.assertRaises(ImportCaseError):
            ensure_local('default')

    def test_management_command_imports_json_and_sanitizes_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'case.json'
            path.write_text(json.dumps(sample_bundle('main'), ensure_ascii=False), encoding='utf-8')
            output = io.StringIO()
            call_command('import_development_case', path, stdout=output)
            self.assertIn('username', json.loads(output.getvalue()))
            path.write_text('PRIVATE_RAW_BROKEN_JSON', encoding='utf-8')
            with self.assertRaises(CommandError) as caught:
                call_command('import_development_case', path)
            self.assertNotIn('PRIVATE_RAW', str(caught.exception))
