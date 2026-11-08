from django.core.exceptions import ValidationError
from .forms import PersonalForm, FinanceForm, MotivationForm
from .services import validate_submission


def incomplete_sections(app):
    try:
        validate_submission(app)
        errors = {}
    except ValidationError as exc:
        errors = exc.message_dict if hasattr(exc, 'message_dict') else {}
    sections = []
    for key, label, cls in [('personal', 'Участник и финал', PersonalForm), ('finance', 'Финансирование', FinanceForm), ('motivation', 'Мотивация', MotivationForm)]:
        fields = set(cls.base_fields)
        fields.update(['profiles'] if key == 'personal' else ['universities', 'specializations', 'achievements'] if key == 'motivation' else [])
        sections.append({'key': key, 'label': label, 'errors': {name: value for name, value in errors.items() if name in fields}})
    return sections
