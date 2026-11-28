from scholar_form.models import UserInfo

from .forms import CIRCUMSTANCE_CHOICES, POSSIBLE_PAYER_CHOICES, PREPARATION_CHOICES, PREVIOUS_PAYER_CHOICES, MATERIAL_CHOICES
from .models import NtoApplication


LABELS = [
    ("last_name", "Фамилия"), ("first_name", "Имя"), ("middle_name", "Отчество"),
    ("region", "Субъект РФ"), ("city", "Город проживания"), ("school_class", "Класс"),
    ("phone", "Телефон"), ("email", "Email"), ("telegram", "Telegram"),
    ("is_adult", "Исполнилось 18 лет"), ("parent_name", "Родитель или представитель"),
    ("parent_phone", "Телефон родителя"), ("final_city", "Город финала"),
    ("previous_final", "Ранее проходил в финал"), ("previous_payers", "Прежняя оплата"),
    ("possible_payers", "Возможные источники оплаты"), ("school_support", "Ответ школы"),
    ("parent_support", "Ответ родителей"), ("ticket_cost", "Стоимость билетов, ₽"),
    ("income_per_member", "Доход на человека, ₽/мес"),
    ("income_proof", "Готовность подтвердить доход"), ("family_material_status", "Материальное положение"),
    ("circumstances", "Жизненные обстоятельства"), ("circumstance_proof", "Готовность подтвердить обстоятельства"),
    ("situation_details", "Описание ситуации"), ("universities", "Приоритетные вузы"),
    ("specializations", "Направления поступления"), ("achievements", "Достижения"),
    ("olympiad_plans", "Олимпиадные планы"),
    ("preparation_methods", "Способы подготовки"), ("preparation_details", "Система подготовки"),
    ("nto_goal", "Цель участия в НТО"), ("refused_olympiads", "Отказывался от олимпиад"),
    ("refusal_reason", "Причина отказа"), ("admission_without_trip", "Поступление без поездки"),
    ("has_admission_advantages", "Есть преимущества при поступлении"),
    ("advantage_details", "Описание преимуществ"), ("free_thoughts", "Свободные мысли"),
]


EVENT_LABELS = {
    "review_saved": "Заключение проверяющего обновлено",
    "marked_read": "Сотрудник подтвердил прочтение",
    "staff_edit": "Анкета отредактирована сотрудником",
    "submitted": "Заявка отправлена",
    "resubmitted": "Отправлена повторно",
    "clarify": "Запрошено уточнение",
    "approve": "Заявка одобрена",
    "reject": "Отказано",
    "internal_note": "Внутренняя заметка обновлена",
    "staff_view": "Карточка просмотрена",
    "export": "Заявка выгружена в XLSX",
}


def event_rows(events):
    statuses = dict(NtoApplication.Status.choices)
    return [{
        "label": EVENT_LABELS.get(event.action, "Другое действие"),
        "actor": (event.actor.get_full_name().strip() or event.actor.get_username()) if event.actor else "Система",
        "created_at": event.created_at,
        "comment": event.comment,
        "transition": f"{statuses.get(event.old_status, '—')} → {statuses.get(event.new_status, '—')}" if event.old_status != event.new_status else "",
    } for event in events]


def answer_rows(app, *, empty="—", separator="; "):
    maps = {
        "previous_payers": dict(PREVIOUS_PAYER_CHOICES),
        "possible_payers": dict(POSSIBLE_PAYER_CHOICES),
        "circumstances": dict(CIRCUMSTANCE_CHOICES),
        "preparation_methods": dict(PREPARATION_CHOICES),
        "school_support": dict(NtoApplication.SupportAnswer.choices),
        "parent_support": dict(NtoApplication.SupportAnswer.choices),
        "income_disclosure": dict(NtoApplication.IncomeDisclosure.choices),
        "family_material_status": {**dict(UserInfo.FamilyMaterialStatus.choices), **dict(MATERIAL_CHOICES)},
    }
    bool_fields = {"is_adult", "finalist_declared", "parent_contact_declared", "previous_final", "income_proof", "circumstance_proof", "no_achievements", "refused_olympiads", "has_admission_advantages"}
    rows = []
    for key, label in LABELS:
        value = getattr(app, key)
        if key == "final_city" and app.status == NtoApplication.Status.DRAFT:
            first_profile = app.ranked_profiles.select_related("profile").order_by("rank").first()
            value = first_profile.profile.final_city if first_profile else ""
        if key in bool_fields:
            value = "Да" if value is True else "Нет" if value is False else empty
        elif isinstance(value, list):
            mapping = maps.get(key, {})
            value = separator.join(mapping.get(item, item) for item in value) or empty
        elif key in maps:
            value = maps[key].get(value, empty)
        elif value is None or value == "":
            value = empty
        rows.append((label, value))
    return rows
