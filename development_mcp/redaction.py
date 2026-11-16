"""Local-only redaction. There is deliberately no best-effort/raw fallback."""

import re
import unicodedata
from dataclasses import dataclass


class RedactionError(Exception):
    pass


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    kind: str


class RussianNER:
    """Load bundled models once. No downloads or external inference at runtime."""

    def __init__(self):
        from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter
        from pymorphy3 import MorphAnalyzer

        self.doc_class = Doc
        self.segmenter = Segmenter()
        self.tagger = NewsNERTagger(NewsEmbedding())
        self.morph = MorphAnalyzer()

    def entities(self, text):
        # Overlap prevents identifiers at an inference boundary from being missed.
        for start in range(0, len(text), 7000):
            chunk = text[max(0, start - 500): start + 7500]
            origin = max(0, start - 500)
            doc = self.doc_class(chunk)
            doc.segment(self.segmenter)
            doc.tag_ner(self.tagger)
            for span in doc.spans:
                kind = {"PER": "person", "LOC": "place", "ORG": "organization"}.get(span.type)
                if kind:
                    yield Entity(origin + span.start, origin + span.stop, kind)

    def lemma(self, token):
        return self.morph.parse(token)[0].normal_form

    def forms(self, token, kind):
        parsed = self.morph.parse(token)
        if kind in {"person", "participant"}:
            parsed = [p for p in parsed if {"Name", "Surn", "Patr"} & set(p.tag.grammemes)] or parsed[:1]
        else:
            parsed = parsed[:1]
        return {form.word for p in parsed for form in p.lexeme}


# Keep monetary amounts untouched unless explicitly labelled as a document/contact.
RULES = tuple((re.compile(pattern, re.I | re.U), label) for pattern, label in (
    (r"(?:https?://|ftp://|www\.|(?:t|vk)\.me/|vk\.com/|disk\.yandex\.[a-z]+/)[^\s<>\[\]]+", "[Ссылка]"),
    (r"(?<![\w@])(?:[a-zа-яё0-9-]+\.)+[a-zа-яё]{2,24}(?:/[^\s<>\[\]]*)?", "[Ссылка]"),
    (r"\b[\w.+-]+@[\w.-]+\.[\w-]{2,}\b", "[Контакт]"),
    (r"(?<!\w)@[\w.]{3,}", "[Контакт]"),
    (r"(?<!\w)(?:\+?7|8)[\s().-]*(?:\d[\s().-]*){9}\d(?!\d)", "[Телефон]"),
    (r"(?<!\w)\+\d(?:[\s().-]*\d){7,14}(?!\d)", "[Телефон]"),
    (r"\b\d{3}[- ]\d{3}[- ]\d{3}[ -]\d{2}\b", "[Документ]"),
    (r"\b\d{4}\s+\d{6}\b", "[Документ]"),
    (r"(?<!\d)(?:\d[ -]?){15,19}\d(?!\d)", "[Реквизиты]"),
    (r"\b(?:паспорт\w*|снилс|инн|бик|кпп|р/с|к/с|сч[её]т\w*|карт[аыу])\s*[:№#-]?\s*\d[\d -]{5,24}\d", "[Реквизиты]"),
    (r"\b(?:ул(?:ица|ице|ицу)?\.?|проспект\w*|пр-т|переулок|пер\.|шоссе|наб\.)\s+[А-ЯЁA-Z0-9][^\n;!?]{0,100}?\d+[а-яa-z]?(?:\s*[,/]?\s*(?:д\.?|дом|кв\.?|квартира|корп\.?|строение)\s*\d+[а-яa-z]?)*", "[Адрес]"),
    (r"\b(?:школ[ауые]|лицей\w*|гимнази[яию])\s*(?:№|номер|no\.?)?\s*\d+[а-я]?", "[Организация]"),
    # Exact calendar dates in prose can identify birth dates even without a label.
    (r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b", "[Дата]"),
    (r"\b\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}\b", "[Дата]"),
    (r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(?:19|20)\d{2}(?:\s*г(?:ода|\.)?)?", "[Дата]"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[Сетевой адрес]"),
))

TOKENS = re.compile(r"[а-яёa-z]+(?:-[а-яёa-z]+)*", re.I)
LABELS = {"participant": "Участник", "person": "Человек", "place": "Место", "organization": "Организация",
          "contact": "Контакт", "document": "Документ", "address": "Адрес", "bank": "Реквизиты"}


def normalize(text):
    return unicodedata.normalize("NFKC", text).replace("\u200b", "").replace("\ufeff", "").replace("ё", "е").replace("Ё", "Е")


class Cleaner:
    def __init__(self, ner):
        self.ner = ner
        self.exact = {}
        self.aliases = {}
        self.counters = {}
        self.detected = {}

    def _label(self, kind):
        if kind in {"participant", "contact", "document", "address", "bank"}:
            return f"[{LABELS[kind]}]"
        self.counters[kind] = self.counters.get(kind, 0) + 1
        return f"[{LABELS[kind]} {self.counters[kind]}]"

    def register(self, value, kind):
        if not value or not isinstance(value, str):
            return
        value = normalize(value).strip()
        if not value:
            return
        tokens = TOKENS.findall(value)
        # A shared surname/first name alone must not turn a parent into the participant.
        # Reuse a compound entity only when every meaningful token agrees.
        meaningful = [token for token in tokens if len(token) >= 3]
        existing = [self.exact.get(token.casefold()) for token in meaningful]
        agreed = existing[0] if existing and existing[0] and len(set(existing)) == 1 else None
        label = self.exact.get(value.casefold()) or agreed or self._label(kind)
        self.exact.setdefault(value.casefold(), label)
        if kind in {"participant", "person", "place", "organization"}:
            for token in tokens:
                if len(token) < 3:
                    continue
                for form in self.ner.forms(token, kind) | {token.casefold()}:
                    self.aliases.setdefault((kind, normalize(form).casefold()), label)
                    self.exact.setdefault(normalize(form).casefold(), label)

    def prepare(self, texts):
        """Discover across the complete case before cutting any continuation page."""
        try:
            for text in texts:
                text = normalize(text)
                if text in self.detected:
                    continue
                spans = list(self.ner.entities(text))
                for span in spans:
                    if not 0 <= span.start < span.end <= len(text) or span.kind not in LABELS:
                        raise RedactionError()
                    self.register(text[span.start:span.end], span.kind)
                self.detected[text] = spans
        except Exception:
            raise RedactionError("redaction_failed") from None

    def clean(self, raw):
        return self.clean_with_spans(raw)[0]

    def clean_with_spans(self, raw):
        """Return cleaned text and normalized-input ranges for local quality checks."""
        try:
            text = normalize(raw)
            if text not in self.detected:
                raise RedactionError()
            replacements = []
            for pattern, label in RULES:
                replacements.extend((m.start(), m.end(), label) for m in pattern.finditer(text))
            # Whole known values (addresses, compound names, account numbers) first.
            for value, label in self.exact.items():
                pattern = re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", re.I)
                replacements.extend((m.start(), m.end(), label) for m in pattern.finditer(text))
            for span in self.detected[text]:
                label = self.exact[text[span.start:span.end].casefold()]
                replacements.append((span.start, span.end, label))
            # Merge overlapping sensitive spans rather than leaking a remaining suffix.
            merged = []
            for start, end, label in sorted(replacements, key=lambda r: (r[0], -(r[1] - r[0]))):
                if merged and start < merged[-1][1]:
                    old_start, old_end, old_label = merged[-1]
                    merged[-1] = (old_start, max(end, old_end), old_label)
                else:
                    merged.append((start, end, label))
            result, offset = [], 0
            for start, end, label in merged:
                result.extend((text[offset:start], label))
                offset = end
            result.append(text[offset:])
            return "".join(result), tuple(merged)
        except Exception:
            raise RedactionError("redaction_failed") from None
