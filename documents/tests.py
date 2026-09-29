from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from scholar_form.models import UserInfo

from .forms import AttachDocumentsForm
from .models import Document, DocumentInstruction, DocumentType


class DocumentInstructionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="documents-instruction")
        UserInfo.objects.create(user=self.user, status="SCHOLAR")
        self.client.force_login(self.user)

    def test_active_instruction_is_shown(self):
        DocumentInstruction.objects.create(
            title="Как загрузить документы",
            text="Подготовьте читаемые сканы.",
            url="https://example.com/documents",
            button_text="Читать правила",
        )

        response = self.client.get(reverse("documents_dashboard"))

        self.assertContains(response, "Как загрузить документы")
        self.assertContains(response, "Подготовьте читаемые сканы.")
        self.assertContains(response, "https://example.com/documents")
        self.assertContains(response, "Читать правила")

    def test_inactive_instruction_is_hidden(self):
        DocumentInstruction.objects.create(
            title="Скрытая инструкция",
            is_active=False,
        )

        response = self.client.get(reverse("documents_dashboard"))

        self.assertNotContains(response, "Скрытая инструкция")


class DocumentTrackAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.main_type = DocumentType.objects.create(name="Только основной трек")
        cls.shared_type = DocumentType.objects.create(
            name="Для обоих треков",
            audience=DocumentType.Audience.ALL,
        )
        cls.alternative_type = DocumentType.objects.create(
            name="Только альтернативный трек",
            audience=DocumentType.Audience.ALTERNATIVE,
        )

    def make_user(self, username, status):
        user = get_user_model().objects.create_user(username=username)
        UserInfo.objects.create(user=user, status=status)
        return user

    def test_scholar_sees_all_document_types(self):
        user = self.make_user("documents-scholar", "SCHOLAR")
        self.client.force_login(user)

        response = self.client.get(reverse("documents_dashboard"))

        self.assertContains(response, "Только основной трек")
        self.assertContains(response, "Для обоих треков")
        self.assertNotContains(response, "Только альтернативный трек")

    def test_alternative_only_sees_allowed_document_types(self):
        user = self.make_user("documents-alternative", "ALTERNATIVE")
        self.client.force_login(user)

        response = self.client.get(reverse("documents_dashboard"))

        self.assertNotContains(response, "Только основной трек")
        self.assertContains(response, "Для обоих треков")
        self.assertContains(response, "Только альтернативный трек")
        self.assertContains(response, reverse("documents_dashboard"))

    def test_alternative_cannot_access_or_change_hidden_slot_document(self):
        user = self.make_user("documents-hidden", "ALTERNATIVE")
        document = Document.objects.create(
            user=user,
            document_type=self.main_type,
            caption=self.main_type.name,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("documents_dashboard"),
            {
                "form_type": "slot_document_form",
                "document_type_id": self.main_type.pk,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.get(reverse("serve_document", args=[document.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("delete_document", args=[document.pk])).status_code,
            403,
        )
        self.assertTrue(Document.objects.filter(pk=document.pk, is_deleted=False).exists())
        self.assertNotIn(document, AttachDocumentsForm(user=user).fields["documents_to_attach"].queryset)

    def test_program_user_cannot_access_alternative_only_document(self):
        user = self.make_user("documents-program-hidden", "SCHOLAR")
        document = Document.objects.create(
            user=user,
            document_type=self.alternative_type,
            caption=self.alternative_type.name,
        )
        self.client.force_login(user)

        self.assertEqual(
            self.client.get(reverse("serve_document", args=[document.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("delete_document", args=[document.pk])).status_code,
            403,
        )
