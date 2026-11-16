import unittest

from development_mcp.redaction import Cleaner, RedactionError, RussianNER
from .helpers import NoNER


class RuleTests(unittest.TestCase):
    def clean(self, text):
        cleaner = Cleaner(NoNER())
        cleaner.prepare([text])
        return cleaner.clean(text)

    def test_contacts_addresses_documents_and_dates(self):
        samples = ['+7 (999) 123-45-67', '8 999 123 45 67', 'ivan@example.org', '@ivanov',
                   'https://disk.yandex.ru/d/PRIVATE', '123-456-789 01', '1234 567890',
                   '40817810099910004312', 'ул. Ленина, д. 10, кв. 5', 'школа №123',
                   '12.03.2009', '2009-03-12', '12 марта 2009 года', 'ИНН 123456789012', '192.168.1.10',
                   '+375 (29) 123-45-67', 'drive.google.com/file/d/PRIVATE']
        for sample in samples:
            with self.subTest(sample=sample):
                result = self.clean('Данные: ' + sample + '. Хочу учиться.')
                self.assertNotIn(sample, result)
                self.assertIn('Хочу учиться.', result)

    def test_preserves_money_and_meaning(self):
        text = 'Доход 12345 рублей, билет стоит 25000. Хочу изучать медицину.'
        self.assertEqual(self.clean(text), text)

    def test_fail_closed(self):
        class Broken(NoNER):
            def entities(self, text):
                raise RuntimeError('PRIVATE_SOURCE_TEXT')
        cleaner = Cleaner(Broken())
        with self.assertRaisesRegex(RedactionError, '^redaction_failed$'):
            cleaner.prepare(['PRIVATE_SOURCE_TEXT'])
        with self.assertRaises(RedactionError):
            Cleaner(NoNER()).clean('Never prepared')

    def test_known_entities_and_unicode(self):
        cleaner = Cleaner(NoNER())
        cleaner.register('Иван', 'participant')
        cleaner.register('ivan_login', 'contact')
        text = 'Иван, ivan_login, ivan@exam\u200bple.org'
        cleaner.prepare([text])
        result = cleaner.clean(text)
        self.assertNotIn('Иван', result)
        self.assertNotIn('ivan', result)


class RealRussianNERTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ner = RussianNER()

    def test_known_names_in_different_cases(self):
        cleaner = Cleaner(self.ner)
        cleaner.register('Иван', 'participant')
        cleaner.register('Иванов', 'participant')
        cleaner.register('Томск', 'place')
        texts = ['Письмо Ивана Иванова из Томска.', 'Я встретил Ивана в Томске. Иванов мечтает стать врачом.']
        cleaner.prepare(texts)
        for text in texts:
            result = cleaner.clean(text)
            self.assertNotRegex(result, r'Иван|Томск')
            self.assertIn('[Участник]', result)

    def test_discovers_unknown_people_locations_and_organizations(self):
        text = 'Сергей Петров приехал из Москвы. Он работает в Газпроме.'
        cleaner = Cleaner(self.ner)
        cleaner.prepare([text])
        result = cleaner.clean(text)
        self.assertNotIn('Сергей', result)
        self.assertNotIn('Петров', result)
        self.assertNotIn('Москвы', result)
        self.assertNotIn('Газпроме', result)

    def test_identity_at_ner_chunk_boundary(self):
        text = ('Хочу учиться. ' * 538) + 'Иван Иванов из Томска. ' + ('Готов заниматься. ' * 60)
        cleaner = Cleaner(self.ner)
        cleaner.register('Иван', 'participant')
        cleaner.register('Иванов', 'participant')
        cleaner.register('Томск', 'place')
        cleaner.prepare([text])
        self.assertNotRegex(cleaner.clean(text), r'Иван|Томск')

    def test_parent_with_shared_surname_is_a_distinct_person(self):
        cleaner = Cleaner(self.ner)
        cleaner.register('Иван', 'participant')
        cleaner.register('Иванов', 'participant')
        cleaner.register('Анна Иванова', 'person')
        text = 'Иван Иванов и его мама Анна Иванова.'
        cleaner.prepare([text])
        result = cleaner.clean(text)
        self.assertIn('[Участник]', result)
        self.assertIn('[Человек 1]', result)
        self.assertNotRegex(result, r'Иван|Анна')
