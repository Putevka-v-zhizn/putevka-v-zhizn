import re
import json
from decimal import Decimal

from django import forms
from django.db.models import Q

from scholar_form.models import UserInfo
from .models import NtoApplication, NtoCampaign, NtoProfile
from .validators import normalize_phone


PAYER_CHOICES = [
    ("region", "Регион"), ("municipality", "Муниципалитет"),
    ("school", "Школа"), ("parents", "Родители"),
    ("profile_partners", "Партнёры профиля"), ("ngo", "Другие НКО / АНО"),
]
PREVIOUS_PAYER_CHOICES = PAYER_CHOICES + [("local", "Финал проходил в моём городе"), ("unknown", "Не знаю")]
POSSIBLE_PAYER_CHOICES = PAYER_CHOICES + [("not_needed", "Оплата не потребуется (финал проходит в моём городе)"), ("unknown", "Не знаю"), ("none", "Никто из перечисленных")]
CIRCUMSTANCE_CHOICES = [
    ("low_income", "Доход семьи ниже прожиточного минимума в регионе"),
    ("large_family", "Многодетная семья"),
    ("single_parent", "Единственный или одинокий родитель"),
    ("breadwinner_loss", "Потеря кормильца"),
    ("unpaid_alimony", "Развод родителей и невыплата алиментов"),
    ("guardianship", "Я ребёнок под опекой"),
    ("own_disability", "У меня есть инвалидность"),
    ("relative_disability", "У близкого члена семьи есть инвалидность (родители, сёстры/братья)"),
    ("parent_pensioner", "Родители — неработающие пенсионеры"),
    ("parent_unemployed", "Один или оба родителя сейчас не работают"),
    ("tickets_quarter", "Билеты дороже четверти дохода семьи"),
    ("other", "Иные обстоятельства"),
    ("none", "Ничего из перечисленного"),
]
MATERIAL_CHOICES = [
    ("w1", "Не хватает денег на еду"),
    ("w2", "На еду хватает, на одежду — нет"),
    ("w3", "На еду и одежду хватает, на мелкую бытовую технику — нет"),
    ("w4", "Хватает на еду, одежду, мелкую бытовую технику и другие покупки"),
]
PREPARATION_CHOICES = [
    ("team", "Состоишь в олимпиадной сборной"),
    ("camps", "Ездил на олимпиадные смены"),
    ("school", "В школе есть олимпиадные занятия"),
    ("tutor", "Дополнительно занимаюсь с репетитором"),
    ("paid_courses", "Дополнительно занимаюсь на платных онлайн или очных курсах"),
    ("self_study", "Дополнительно занимаюсь самостоятельно по бесплатным / открытым источникам и книгам"),
]
BOOL_CHOICES = [("", "— Выберите —"), ("yes", "Да"), ("no", "Нет")]


def bool_field(label):
    return forms.TypedChoiceField(
        label=label, choices=BOOL_CHOICES, required=False,
        coerce=lambda value: {"yes": True, "no": False}.get(value), empty_value=None,
    )


def exclusive(values, special):
    if len(set(values)) != len(values):
        raise forms.ValidationError("Одинаковый вариант выбран несколько раз.")
    if len(values) > 1 and set(values) & set(special):
        raise forms.ValidationError("Этот вариант нельзя сочетать с другими.")


class DraftModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
            if isinstance(field.widget, (forms.TextInput, forms.EmailInput, forms.NumberInput, forms.Textarea, forms.Select)):
                field.widget.attrs.setdefault("class", "form-control")


class PersonalForm(DraftModelForm):
    is_adult = bool_field("Тебе уже исполнилось 18 лет?")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["is_adult"] = "yes" if self.instance.is_adult is True else "no" if self.instance.is_adult is False else ""

    class Meta:
        model = NtoApplication
        fields = ["last_name", "first_name", "middle_name", "region", "city", "school_class", "phone", "telegram", "is_adult", "parent_name", "parent_phone"]
        labels = {
            "last_name": "Фамилия", "first_name": "Имя", "middle_name": "Отчество (при наличии)",
            "region": "Субъект РФ", "city": "Населённый пункт", "phone": "Телефон участника",
            "telegram": "Telegram",
            "school_class": "Класс", "parent_name": "ФИО родителя или законного представителя",
            "parent_role": "Кем он приходится участнику", "parent_phone": "Телефон родителя",
            "finalist_declared": "Подтверждаю выход в финал НТО по выбранным профилям",
            "parent_contact_declared": "Подтверждаю, что родитель или законный представитель знает о заявке и разрешает указать свой контакт",
        }
        widgets = {key: forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "placeholder": "+7 (903) 123-45-67"}) for key in ("phone", "parent_phone")}

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get("phone"))

    def clean_parent_phone(self):
        return normalize_phone(self.cleaned_data.get("parent_phone"))

    def clean_telegram(self):
        value = (self.cleaned_data.get("telegram") or "").strip().lstrip("@")
        if value and not re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
            raise forms.ValidationError("Укажите имя Telegram без ссылки, от 5 до 32 символов.")
        return value


class ProfileRankingForm(forms.Form):
    profile_order = forms.JSONField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, campaign, application=None, **kwargs):
        super().__init__(*args, **kwargs)
        existing = list(application.ranked_profiles.order_by("rank").values_list("profile_id", flat=True)) if application and application.pk else []
        self.profiles = list(NtoProfile.objects.filter(campaign=campaign).filter(
            Q(is_active=True) | Q(pk__in=existing)
        ).order_by("name"))
        self.profile_map = {str(profile.pk): profile for profile in self.profiles}
        self.initial.setdefault("profile_order", [str(pk) for pk in existing])

    def clean_profile_order(self):
        if self.is_bound and "profile_order" not in self.data:
            raise forms.ValidationError("Обновите страницу и выберите профили заново.")
        values = self.cleaned_data.get("profile_order")
        if values is None:
            values = []
        if not isinstance(values, list) or len(values) > len(self.profiles) or any(type(value) not in (str, int) for value in values):
            raise forms.ValidationError("Некорректный список профилей.")
        ids = [str(value) for value in values]
        if len(set(ids)) != len(ids):
            raise forms.ValidationError("Профиль выбран повторно.")
        if any(pk not in self.profile_map for pk in ids):
            raise forms.ValidationError("Выберите доступные профили этого сезона.")
        self.selected_profiles = [self.profile_map[pk] for pk in ids]
        return ids

    @property
    def selected_ids(self):
        if not self.is_bound:
            return self.initial["profile_order"]
        try:
            values = json.loads(self.data.get("profile_order", "[]"))
        except (TypeError, ValueError):
            return []
        if not isinstance(values, list):
            return []
        return list(dict.fromkeys(str(value) for value in values if type(value) in (str, int) and str(value) in self.profile_map))

    @property
    def selected_profile_rows(self):
        return [self.profile_map[pk] for pk in self.selected_ids]

    @property
    def picker_data(self):
        return {"profiles": [
            {"id": str(profile.pk), "name": profile.name, "city": profile.final_city, "active": profile.is_active}
            for profile in self.profiles
        ], "selected": self.selected_ids}


class MoneyField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = re.sub(r"\s+", "", value).replace(",", ".")
        return super().to_python(value)


class FinanceForm(DraftModelForm):
    ticket_cost = MoneyField(
        required=False, min_value=0, max_value=10000000, decimal_places=0,
        label="Стоимость билетов туда и обратно, ₽",
        widget=forms.TextInput(attrs={"inputmode": "numeric"}),
        error_messages={"max_decimal_places": "Укажи сумму в целых рублях, без копеек."},
    )
    income_per_member = MoneyField(
        required=False, min_value=0, max_digits=12, decimal_places=2,
        label="Доход на одного члена семьи в месяц, ₽",
        widget=forms.TextInput(attrs={"inputmode": "decimal"}),
    )
    previous_final = bool_field("Проходил(а) ли раньше в финал НТО?")
    previous_payers = forms.MultipleChoiceField(choices=PREVIOUS_PAYER_CHOICES, widget=forms.CheckboxSelectMultiple, required=False, label="Кто оплачивал проезд раньше?")
    possible_payers = forms.MultipleChoiceField(choices=POSSIBLE_PAYER_CHOICES, widget=forms.CheckboxSelectMultiple, required=False, label="Из каких средств может быть оплачен проезд?")
    income_proof = bool_field("Сможешь подтвердить доход документами?")
    circumstance_proof = bool_field("Сможешь подтвердить обстоятельства документами?")
    circumstances = forms.MultipleChoiceField(choices=CIRCUMSTANCE_CHOICES, widget=forms.CheckboxSelectMultiple, required=False, label="Жизненные обстоятельства")

    class Meta:
        model = NtoApplication
        fields = ["previous_final", "previous_payers", "possible_payers", "school_support", "parent_support", "ticket_cost", "income_per_member", "income_proof", "family_material_status", "circumstances", "circumstance_proof", "situation_details"]
        labels = {"ticket_cost": "Стоимость билетов туда и обратно, ₽", "income_per_member": "Доход на одного члена семьи в месяц, ₽", "family_material_status": "Материальное положение семьи", "situation_details": "Расскажи о жизненной ситуации (до 1000 знаков)"}
        widgets = {"situation_details": forms.Textarea(attrs={"rows": 4, "maxlength": 1000})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["family_material_status"] = forms.ChoiceField(
            choices=[("", "— Выберите —")] + MATERIAL_CHOICES + ([(self.instance.family_material_status, "Ранее выбранный вариант — выбери актуальное описание")] if self.instance.family_material_status and self.instance.family_material_status not in dict(MATERIAL_CHOICES) else []),
            required=False, label="Материальное положение семьи",
            initial=self.instance.family_material_status,
            widget=forms.Select(attrs={"class": "form-control"}),
        )
        if not self.is_bound:
            if self.instance.ticket_cost is not None:
                self.initial["ticket_cost"] = round(self.instance.ticket_cost)
            for key in ("previous_final", "income_proof", "circumstance_proof"):
                value = getattr(self.instance, key)
                self.initial[key] = "yes" if value is True else "no" if value is False else ""
        self.fields["school_support"].label = "Какой ответ об оплате проезда ты получил(а) в школе?"
        self.fields["parent_support"].label = "Какой ответ об оплате билетов ты получил(а) от родителей?"
        self.fields["income_per_member"].help_text = "Спроси у родителя / законного представителя."
        for key in ("school_support", "parent_support"):
            self.fields[key].choices = [("", "— Выберите —")] + [(value, label) for value, label in NtoApplication.SupportAnswer.choices if value != "not_discussed"]

    def clean(self):
        data = super().clean()
        for key, special in (("previous_payers", {"local", "unknown"}), ("possible_payers", {"not_needed", "unknown", "none"}), ("circumstances", {"none", "declined"})):
            try:
                exclusive(data.get(key) or [], special)
            except forms.ValidationError as exc:
                self.add_error(key, exc)
        if data.get("previous_final") is not True:
            data["previous_payers"] = []
        if len(data.get("situation_details") or "") > 1000:
            self.add_error("situation_details", "Не более 1000 знаков.")
        return data


class MotivationForm(DraftModelForm):
    universities_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), required=False, label="Приоритетные вузы (до 5, по одному на строке)")
    specializations_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), required=False, label="Направления поступления (до 5)")
    achievements_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), required=False, label="Расскажи про опыт участия в олимпиадах в прошлом году и достижения по данному профилю (до 5 самых значимых)")
    preparation_methods = forms.MultipleChoiceField(choices=PREPARATION_CHOICES, widget=forms.CheckboxSelectMultiple, required=False, label="Отметь все доступные тебе способы подготовки к олимпиадам")
    refused_olympiads = bool_field("Отказывался(ась) ли раньше от участия в олимпиадах?")
    has_admission_advantages = bool_field("Есть ли достижения, дающие существенные преимущества для поступления (100 баллов, БВИ, существенные финансовые призы)?")

    class Meta:
        model = NtoApplication
        fields = ["universities_text", "specializations_text", "achievements_text", "olympiad_plans", "preparation_methods", "preparation_details", "nto_goal", "refused_olympiads", "refusal_reason", "admission_without_trip", "has_admission_advantages", "advantage_details", "free_thoughts"]
        labels = {"no_achievements": "Достижений пока нет", "olympiad_plans": "Расскажи про олимпиадные планы в текущем году: где зарегистрировался, участвовал, прошёл в финал и куда планируешь поехать", "preparation_details": "Как выстроена твоя подготовка в этом году: частота занятий, проделанная работа, источники и основные акценты", "nto_goal": "Цель участия в НТО и важность поездки", "refusal_reason": "Почему отказывался(ась)?", "admission_without_trip": "Что изменится в поступлении без поездки?", "advantage_details": "Какие преимущества уже есть?", "free_thoughts": "Свободные мысли"}
        widgets = {key: forms.Textarea(attrs={"rows": 4}) for key in ("olympiad_plans", "preparation_details", "nto_goal", "refusal_reason", "admission_without_trip", "advantage_details", "free_thoughts")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and not self.is_bound:
            for key in ("universities", "specializations", "achievements"):
                self.fields[f"{key}_text"].initial = "\n".join(getattr(self.instance, key) or [])
            for key in ("refused_olympiads", "has_admission_advantages"):
                value = getattr(self.instance, key)
                self.initial[key] = "yes" if value is True else "no" if value is False else ""

    def clean(self):
        data = super().clean()
        for key in ("universities", "specializations", "achievements"):
            lines = [line.strip() for line in (data.get(f"{key}_text") or "").splitlines() if line.strip()]
            if len(lines) > 5:
                self.add_error(f"{key}_text", "Не более 5 строк.")
            data[key] = lines
        if data.get("refused_olympiads") is not True:
            data["refusal_reason"] = ""
        if data.get("has_admission_advantages") is not True:
            data["advantage_details"] = ""
        return data


class ClarificationForm(forms.Form):
    comment = forms.CharField(label="Что нужно уточнить?", widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}))
    due_at = forms.SplitDateTimeField(label="Срок ответа", widget=forms.SplitDateTimeWidget(date_attrs={"type": "date", "class": "form-control", "aria-label": "Дата срока уточнения"}, time_attrs={"type": "time", "class": "form-control", "aria-label": "Время срока уточнения"}))


class DecisionForm(forms.Form):
    comment = forms.CharField(required=False, label="Комментарий участнику", widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))


class ProfileImportForm(forms.Form):
    file = forms.FileField(label="XLSX со столбцами external_code, name, final_city")

    def clean_file(self):
        file = self.cleaned_data["file"]
        if not file.name.lower().endswith(".xlsx") or file.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Загрузите XLSX не больше 2 МБ.")
        return file
