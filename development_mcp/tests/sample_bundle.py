"""Sanitized portable sample, usable by Django tests without importing MCP/psycopg."""

from datetime import datetime, timezone
import hashlib

from development_mcp.bundle import FORMAT, VERSION
from development_mcp.schema import PROGRAMS, registry_version


def token(value):
    return hashlib.sha256(value.encode()).hexdigest()


def sample_bundle(program):
    participant = token('participant')
    def record(table, fields, links=None):
        return dict(id=token(table), table=table, fields=fields,
                    links={'participant': participant, **{name: token(target) for name, target in (links or {}).items()}})
    records = [record('scholar_form_userinfo', {'form_status': 'submitted', 'selection_step': 'ml', 'age_group': '14_17', 'other_factors': 'Очищенная история [Участник].'})]
    if program == 'family_income':
        records[0]['fields']['status'] = 'FINAL STAGE'
    if program == 'main':
        records += [record('core_motivationletter', {'status': 'revision', 'letter_text': 'Реальное содержание после очистки. ' * 500, 'admin_score': 4}),
                    record('core_motivationletterrubricreview', {'total_score': 7}, {'letter': 'core_motivationletter'}),
                    record('review_by_tutor_interview', {'transcript': '[Участник]: хочу учиться.', 'transcript_status': 'DONE'}),
                    record('review_by_tutor_interviewresult', {'interviewer_score': 5}, {'interview': 'review_by_tutor_interview'}),
                    record('scholar_form_scholarvideo', {'transcript_text': 'Очищенная видеовизитка', 'transcript_status': 'DONE'}),
                    record('review_by_tutor_testassignment', {'title': 'Тест', 'numeric_grade': '4', 'numeric_percentile': 75, 'status': 'assigned'}),
                    record('scholar_form_staffnote', {'text': 'Заметка [Человек 1].'})]
    elif program == 'nto':
        records += [record('nto_travel_ntocampaign', {'academic_year': '2026-2027'}),
                    record('nto_travel_ntoapplication', {'status': 'approved', 'ticket_cost': '15000.00', 'situation_details': 'Очищенная история.', 'achievements': ['Проект']}, {'campaign': 'nto_travel_ntocampaign'}),
                    record('nto_travel_ntoapplicationreview', {'criticality': 4, 'motivation': 5, 'motivation_reason': 'Хочет учиться.'}, {'application': 'nto_travel_ntoapplication'}),
                    record('nto_travel_ntoapplicationprofile', {'rank': 1, 'name_snapshot': 'Робототехника'}, {'application': 'nto_travel_ntoapplication'}),
                    record('nto_travel_ntoapplicationevent', {'action': 'approved', 'new_status': 'approved', 'comment': 'Одобрено'}, {'application': 'nto_travel_ntoapplication'})]
    else:
        records += [record('family_income_familyincomecase', {'status': 'pending_review', 'family_members_count': 3, 'family_members_description': '[Участник] и родители.'}, {'user_info': 'scholar_form_userinfo'}),
                    record('family_income_familyincomedocument', {'category': 'income', 'candidate_comment': 'Комментарий к справке.', 'review_status': 'approved'}, {'case': 'family_income_familyincomecase'}),
                    record('family_income_incomeyear', {'year': 2025}),
                    record('family_income_incomeevidence', {'gross_amount': '123456.00', 'net_amount': '100000.00', 'average_monthly_amount': '8333.33'}, {'family_income_document': 'family_income_familyincomedocument', 'year': 'family_income_incomeyear'}),
                    record('family_income_socialbenefitevidence', {'benefit_description': 'Пособие'}, {'family_income_document': 'family_income_familyincomedocument'}),
                    record('family_income_familyincomedecision', {'amount_per_member': '12345.00', 'comment': 'Подтверждено'}, {'case': 'family_income_familyincomecase', 'year': 'family_income_incomeyear'})]
    return dict(format=FORMAT, version=VERSION, case_id=token('case-' + program), program=program,
                root_record_id=token(PROGRAMS[program][0]), registry_version=registry_version(),
                data_as_of=datetime.now(timezone.utc).isoformat(), redaction_rules_version='test', automatically_redacted=True, records=records)
