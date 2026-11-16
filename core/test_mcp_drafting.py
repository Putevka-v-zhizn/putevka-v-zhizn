import ast
import io
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from development_mcp.drafting import DraftError, draft_model
from scholar_form.models import StaffNote, UserInfo
from review_by_tutor.models import TestAssignment
from family_income.models import IncomeEvidence


class MCPDraftingTests(TestCase):
    def test_draft_has_live_fields_join_and_privacy_classification_without_queries(self):
        with self.assertNumQueries(0):
            text = draft_model(UserInfo, ('main',))
        ast.parse('draft = {' + text + '}')
        self.assertIn("('first_name', 'person')", text)
        self.assertIn("age_field='birth_date'", text)
        self.assertIn("'auth_user', 'user_id'", text)
        self.assertIn('# Excluded avatar:', text)
        self.assertIn('CaseFilter(', text)
        live = draft_model(TestAssignment, ('main',), 'user')
        self.assertNotIn('score_a', live)

    def test_ambiguous_parent_needs_explicit_choice(self):
        # StaffNote's canonical target_user must be preferred over its author.
        self.assertIn("'target_user_id'", draft_model(StaffNote, ('main',)))
        with self.assertRaises(DraftError):
            draft_model(IncomeEvidence, ('family_income',))
        with self.assertRaises(DraftError):
            draft_model(UserInfo, ('missing',))

    def test_command_writes_only_new_draft_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'draft.py'
            call_command('draft_mcp_model', 'scholar_form.UserInfo', program=['main'], output=path, stdout=io.StringIO())
            original = path.read_bytes()
            with self.assertRaises(CommandError):
                call_command('draft_mcp_model', 'scholar_form.UserInfo', program=['main'], output=path)
            self.assertEqual(path.read_bytes(), original)
