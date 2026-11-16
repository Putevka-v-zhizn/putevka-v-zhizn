from contextlib import contextmanager
from copy import deepcopy

from development_mcp.database import Reader
from development_mcp.schema import PROGRAMS, case_filters, filter_path
from development_mcp.selection import normalize_filters


class NoNER:
    """Only for deterministic rule/transport tests; production never uses this."""

    def entities(self, text):
        return []

    def forms(self, token, kind):
        return {token.casefold()}


class MemoryReader(Reader):
    def __init__(self, data):
        super().__init__(None)
        self.data = data

    def select(self, table, column=None, values=(), *, columns=None, limit=501, offset=0, status=None):
        rows = [deepcopy(row) for row in self.data.get(table, [])
                if (not column or row.get(column) in values) and (not status or row.get(status[0]) == status[1])]
        rows.sort(key=lambda row: row['id'])
        rows = rows[offset:offset + limit]
        if columns:
            rows = [{column: row[column] for column in columns} for row in rows]
        return rows

    def root_ids(self, program):
        return (row['id'] for row in self.data.get(PROGRAMS[program][0], []))

    def list_roots(self, program, status, offset, limit, filters=None):
        filters = normalize_filters(program, filters)
        table, status_field, _ = PROGRAMS[program]
        result = []
        for root in sorted(self.data.get(table, []), key=lambda row: row['id']):
            if status is not None and root.get(status_field) != status:
                continue
            row = {'id': root['id'], status_field: root.get(status_field)}
            for name, (target, definition) in case_filters(program).items():
                related = [root]
                for next_table, load in filter_path(program, target):
                    source_values = {item.get(load.source_column) for item in related} - {None}
                    related = [item for item in self.data.get(next_table, []) if item.get(load.column) in source_values]
                if definition.kind == 'count':
                    value = len({item['id'] for item in related})
                elif definition.kind == 'text':
                    value = any((item.get(definition.field) or '').strip() for item in related)
                elif definition.kind == 'number':
                    value = max((item[definition.field] for item in related if item.get(definition.field) is not None), default=None)
                else:
                    value = sorted({item[definition.field] if item[definition.field] in definition.choices else 'unknown'
                                    for item in related if item.get(definition.field) not in (None, '')})
                row['feature_' + name] = value
            matches = True
            for name, value in filters.items():
                actual = row['feature_' + name]
                kind = case_filters(program)[name][1].kind
                if kind == 'choice':
                    matches &= value in actual
                elif kind == 'text':
                    matches &= value == actual
                else:
                    matches &= actual is not None and ('min' not in value or actual >= value['min']) and ('max' not in value or actual <= value['max'])
            if matches:
                result.append(row)
        return result[offset:offset + limit]


class MemoryDatabase:
    def __init__(self, data):
        self.data, self.reads = data, 0

    @contextmanager
    def read(self):
        self.reads += 1
        yield MemoryReader(self.data)


def fixture():
    return {
        'auth_user': [{'id': 101, 'first_name': 'Иван', 'last_name': 'Иванов', 'email': 'ivan@example.org', 'username': 'ivan_login'}],
        'scholar_form_userinfo': [{'id': 201, 'user_id': 101, 'form_status': 'submitted', 'first_name': 'Иван', 'last_name': 'Иванов',
                                   'city': 'Томск', 'phone': '+79991234567', 'other_factors': 'Иван из Томска. Телефон +79991234567',
                                   'password': 'NEVER_OUTPUT_PASSWORD', 'future_field': 'NEVER_OUTPUT_UNKNOWN'}],
        'scholar_form_userpersonaldata': [{'id': 301, 'user_id': 101, 'bank_account': '40817810099910004312'}],
        'core_motivationletter': [{'id': 401, 'user_id': 101, 'status': 'submitted', 'letter_text': 'Я Иван Иванов. Мой счёт 40817810099910004312. Хочу стать врачом.', 'admin_score': 4}],
        'core_motivationletterrubricreview': [{'id': 402, 'letter_id': 401, 'total_score': 7, 'reviewer_comment': 'Содержательная мотивация.'}],
        'review_by_tutor_interview': [{'id': 501, 'user_id': 101, 'notes': 'Живёт в Томск', 'transcript': 'Здравствуйте, я Иван.', 'transcript_error': 'RAW_EXCEPTION_SECRET'}],
        'review_by_tutor_interviewresult': [{'id': 502, 'interview_id': 501, 'interviewer_score': 4, 'other_notes': 'Учится хорошо'}],
        'nto_travel_ntoapplication': [{'id': 601, 'user_id': 101, 'campaign_id': 602, 'status': 'approved', 'first_name': 'Иван', 'last_name': 'Иванов',
                                     'situation_details': 'Мой телефон +79991234567', 'ticket_cost': 15000,
                                     'achievements': [{'ivan_login': 'Письмо ivan@example.org'}]}],
        'nto_travel_ntocampaign': [{'id': 602, 'academic_year': '2026-2027'}],
        'nto_travel_ntoapplicationreview': [{'id': 603, 'application_id': 601, 'criticality': 4, 'criticality_reason': 'Сложная ситуация'}],
        'nto_travel_ntoapplicationprofile': [{'id': 604, 'application_id': 601, 'rank': 1, 'name_snapshot': 'Робототехника', 'city_snapshot': 'Томск'}],
        'nto_travel_ntoapplicationevent': [{'id': 605, 'application_id': 601, 'action': 'approved', 'comment': 'Одобрено'}],
        'family_income_familyincomecase': [{'id': 701, 'user_info_id': 201, 'status': 'pending_review', 'family_members_count': 3, 'family_members_description': 'Иван и родители'}],
        'family_income_familyincomedocument': [{'id': 702, 'case_id': 701, 'document_id': 900, 'category': 'income', 'candidate_comment': 'Справка', 'file': 'PRIVATE_FILE'}],
        'family_income_incomeevidence': [{'id': 703, 'family_income_document_id': 702, 'year_id': 704, 'owner_name': 'Мария Петрова', 'gross_amount': 123456,
                                        'staff_decision_comment': 'Мария Петрова получила 123456 рублей'}],
        'family_income_incomeyear': [{'id': 704, 'year': 2025}],
        'family_income_socialbenefitevidence': [{'id': 705, 'family_income_document_id': 702, 'recipient_name': 'Мария Петрова', 'benefit_description': 'Пособие'}],
        'family_income_familyincomedecision': [{'id': 706, 'case_id': 701, 'year_id': 704, 'amount_per_member': 12345, 'comment': 'Подтверждено'}],
    }
