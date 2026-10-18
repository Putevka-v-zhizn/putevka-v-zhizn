import re
from decimal import Decimal

from django import forms

from scholar_form.models import UserInfo
from .models import NtoApplication, NtoCampaign, NtoProfile


PAYER_CHOICES = [
    ("region", "Регион"), ("municipality", "Муниципалитет"),
    ("school", "Школа"), ("parents", "Родители"),
    ("profile_partners", "Партнёры профиля"), ("ngo", "Другие НКО / АНО"),
]
PREVIOUS_PAYER_CHOICES = PAYER_CHOICES + [("local", "Финал проходил в моём городе"), ("unknown", "Не знаю")]
POSSIBLE_PAYER_CHOICES = PAYER_CHOICES + [("not_needed", "Оплата не потребуется"), ("unknown", "Не знаю"), ("none", "Никто из перечисленных")]
CIRCUMSTANCE_CHOICES = [
    ("low_income", "Доход семьи ниже прожиточного минимума в регионе"),
    ("large_family", "Многодетная семья"),
    ("single_parent", "Единственный или одинокий родитель"),
    ("breadwinner_loss", "Потеря кормильца"),
    ("unpaid_alimony", "Развод родителей и невыплата алиментов"),
    ("guardianship", "Я ребёнок под опекой"),
    ("own_disability", "У меня есть инвалидность"),
    ("relative_disability", "У близкого члена семьи есть инвалидность"),
    ("parent_pensioner", "Родители — неработающие пенсионеры"),
    ("parent_unemployed", "Один или оба родителя сейчас не работают"),
    ("tickets_quarter", "Билеты дороже четверти дохода семьи"),
    ("other", "Иные обстоятельства"),
    ("none", "Ничего из перечисленного"),
    ("declined", "Не хочу отвечать"),
]
PREPARATION_CHOICES = [
    ("team", "Олимпиадная сборная"), ("camps", "Олимпиадные смены"),
    ("school", "Занятия в школе"), ("tutor", "Репетитор"),
    ("paid_courses", "Платные курсы"),
    ("self_study", "Самостоятельно по открытым источникам и книгам"),
    ("none", "Ничего из перечисленного"),
]
BOOL_CHOICES = [("", "— Выберите —"), ("yes", "Да"), ("no", "Нет")]


def bool_field(label):
    return forms.TypedChoiceField(
        label=label, choices=BOOL_CHOICES, required=False,
        coerce=lambda value: {"yes": True, "no": False}.get(value), empty_value=None,
    )


def normalize_phone(value):
    value = (value or "").strip()
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15:
        raise forms.ValidationError("Укажите телефон: от 10 до 15 цифр.")
    return "+" + digits


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
    class Meta:
        model = NtoApplication
        fields = ["last_name", "first_name", "middle_name", "region", "city", "school_class", "phone", "telegram", "parent_name", "parent_role", "parent_phone", "finalist_declared", "parent_contact_declared"]
        labels = {
            "last_name": "Фамилия", "first_name": "Имя", "middle_name": "Отчество (при наличии)",
            "region": "Субъект РФ", "city": "Населённый пункт", "phone": "Телефон участника",
            "telegram": "Telegram (необязательно)",
            "school_class": "Класс", "parent_name": "ФИО родителя или законного представителя",
            "parent_role": "Кем он приходится участнику", "parent_phone": "Телефон родителя",
            "finalist_declared": "Я вышел(вышла) в финал НТО по выбранным профилям",
            "parent_contact_declared": "Я сообщил(а) родителю или представителю о заявке и получил(а) разрешение указать контакт",
        }

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
    def __init__(self, *args, campaign, application=None, **kwargs):
        super().__init__(*args, **kwargs)
        existing = {row.profile_id: row.rank for row in application.ranked_profiles.all()} if application and application.pk else {}
        self.profiles = list(NtoProfile.objects.filter(campaign=campaign).filter(is_active=True) | NtoProfile.objects.filter(pk__in=existing))
        self.profiles.sort(key=lambda p: (existing.get(p.pk, 9999), p.name))
        self.profile_fields = []
        for profile in self.profiles:
            self.fields[f"choose_{profile.pk}"] = forms.BooleanField(required=False, label=f"{profile.name} — {profile.final_city}", initial=profile.pk in existing)
            self.fields[f"rank_{profile.pk}"] = forms.IntegerField(required=False, min_value=1, label="Приоритет", initial=existing.get(profile.pk), widget=forms.NumberInput(attrs={"class": "form-control", "style": "max-width: 8rem"}))
            self.profile_fields.append((profile, self[f"choose_{profile.pk}"], self[f"rank_{profile.pk}"]))

    def clean(self):
        data = super().clean()
        selected = []
        for profile in self.profiles:
            checked = data.get(f"choose_{profile.pk}")
            rank = data.get(f"rank_{profile.pk}")
            if checked and rank is None:
                self.add_error(f"rank_{profile.pk}", "Укажите приоритет.")
            if not checked and rank is not None:
                self.add_error(f"rank_{profile.pk}", "Сначала выберите профиль.")
            if checked and rank is not None:
                selected.append((rank, profile))
        ranks = sorted(rank for rank, _ in selected)
        if ranks and ranks != list(range(1, len(ranks) + 1)):
            raise forms.ValidationError("Приоритеты должны идти подряд с 1 без повторов.")
        self.selected_profiles = [profile for _, profile in sorted(selected)]
        return data


class FinanceForm(DraftModelForm):
    previous_final = bool_field("Проходил(а) ли раньше в финал НТО?")
    previous_payers = forms.MultipleChoiceField(choices=PREVIOUS_PAYER_CHOICES, widget=forms.CheckboxSelectMultiple, required=False, label="Кто оплачивал проезд раньше?")
    possible_payers = forms.MultipleChoiceField(choices=POSSIBLE_PAYER_CHOICES, widget=forms.CheckboxSelectMultiple, required=False, label="Из каких средств может быть оплачен проезд?")
    income_proof = bool_field("Сможешь подтвердить доход документами?")
    circumstance_proof = bool_field("Сможешь подтвердить обстоятельства документами?")
    circumstances = forms.MultipleChoiceField(choices=CIRCUMSTANCE_CHOICES, widget=forms.CheckboxSelectMultiple, required=False, label="Жизненные обстоятельства")

    class Meta:
        model = NtoApplication
        fields = ["previous_final", "previous_payers", "possible_payers", "school_support", "parent_support", "ticket_cost", "income_disclosure", "income_per_member", "income_proof", "family_material_status", "circumstances", "circumstance_proof", "situation_details"]
        labels = {"ticket_cost": "Стоимость билетов туда и обратно, ₽", "income_per_member": "Доход на одного члена семьи в месяц, ₽", "family_material_status": "Материальное положение семьи", "situation_details": "Расскажи о жизненной ситуации (до 1000 знаков)"}
        widgets = {"situation_details": forms.Textarea(attrs={"rows": 4, "maxlength": 1000})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["family_material_status"] = forms.ChoiceField(
            choices=[("", "— Выберите —")] + list(UserInfo.FamilyMaterialStatus.choices),
            required=False, label="Материальное положение семьи",
            initial=self.instance.family_material_status,
            widget=forms.Select(attrs={"class": "form-control"}),
        )
        if not self.is_bound:
            for key in ("previous_final", "income_proof", "circumstance_proof"):
                value = getattr(self.instance, key)
                self.initial[key] = "yes" if value is True else "no" if value is False else ""
        self.fields["school_support"].label = "Какой ответ об оплате проезда ты получил(а) в школе?"
        self.fields["parent_support"].label = "Какой ответ об оплате билетов ты получил(а) от родителей?"
        self.fields["income_disclosure"].label = "Готов(а) ли ты указать доход на одного члена семьи?"

    def clean(self):
        data = super().clean()
        for key, special in (("previous_payers", {"local", "unknown"}), ("possible_payers", {"not_needed", "unknown", "none"}), ("circumstances", {"none", "declined"})):
            try:
                exclusive(data.get(key) or [], special)
            except forms.ValidationError as exc:
                self.add_error(key, exc)
        if data.get("previous_final") is not True:
            data["previous_payers"] = []
        if data.get("income_disclosure") != NtoApplication.IncomeDisclosure.AMOUNT:
            data["income_per_member"] = None
            data["income_proof"] = None
        if not (set(data.get("circumstances") or []) - {"none", "declined"}):
            data["circumstance_proof"] = None
        if len(data.get("situation_details") or "") > 1000:
            self.add_error("situation_details", "Не более 1000 знаков.")
        return data


class MotivationForm(DraftModelForm):
    universities_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), required=False, label="Приоритетные вузы (до 5, по одному на строке)")
    specializations_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), required=False, label="Направления поступления (до 5)")
    achievements_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), required=False, label="Достижения прошлого года (до 5)")
    preparation_methods = forms.MultipleChoiceField(choices=PREPARATION_CHOICES, widget=forms.CheckboxSelectMultiple, required=False, label="Способы подготовки")
    refused_olympiads = bool_field("Отказывался(ась) ли раньше от участия в олимпиадах?")
    has_admission_advantages = bool_field("Есть ли значимые преимущества для поступления?")

    class Meta:
        model = NtoApplication
        fields = ["universities_text", "specializations_text", "achievements_text", "no_achievements", "olympiad_plans", "preparation_methods", "preparation_details", "nto_goal", "refused_olympiads", "refusal_reason", "admission_without_trip", "has_admission_advantages", "advantage_details", "free_thoughts"]
        labels = {"no_achievements": "Достижений пока нет", "olympiad_plans": "Олимпиадные планы в этом году", "preparation_details": "Как устроена твоя подготовка", "nto_goal": "Цель участия в НТО и важность поездки", "refusal_reason": "Почему отказывался(ась)?", "admission_without_trip": "Что изменится в поступлении без поездки?", "advantage_details": "Какие преимущества уже есть?", "free_thoughts": "Свободные мысли"}
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
            if len(lines) > 5 or any(len(line) > 300 for line in lines):
                self.add_error(f"{key}_text", "Не более 5 строк по 300 знаков.")
            data[key] = lines
        try:
            exclusive(data.get("preparation_methods") or [], {"none"})
        except forms.ValidationError as exc:
            self.add_error("preparation_methods", exc)
        if data.get("no_achievements") and data["achievements"]:
            self.add_error("achievements_text", "Этот ответ нельзя сочетать с отметкой об отсутствии достижений.")
        if data.get("no_achievements"):
            data["achievements"] = []
        if data.get("refused_olympiads") is not True:
            data["refusal_reason"] = ""
        if data.get("has_admission_advantages") is not True:
            data["advantage_details"] = ""
        for key, limit in (("olympiad_plans", 3000), ("preparation_details", 3000), ("nto_goal", 2000), ("refusal_reason", 1000), ("admission_without_trip", 2000), ("advantage_details", 1000), ("free_thoughts", 1000)):
            if len(data.get(key) or "") > limit:
                self.add_error(key, f"Не более {limit} знаков.")
        return data


class ClarificationForm(forms.Form):
    comment = forms.CharField(label="Что нужно уточнить?", widget=forms.Textarea)
    due_at = forms.SplitDateTimeField(label="Срок ответа", widget=forms.SplitDateTimeWidget(date_attrs={"type": "date", "aria-label": "Дата срока уточнения"}, time_attrs={"type": "time", "aria-label": "Время срока уточнения"}))


class DecisionForm(forms.Form):
    comment = forms.CharField(required=False, label="Комментарий участнику", widget=forms.Textarea)


class ProfileImportForm(forms.Form):
    file = forms.FileField(label="XLSX со столбцами external_code, name, final_city")

    def clean_file(self):
        file = self.cleaned_data["file"]
        if not file.name.lower().endswith(".xlsx") or file.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Загрузите XLSX не больше 2 МБ.")
        return file
