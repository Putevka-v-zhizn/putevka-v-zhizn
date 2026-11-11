from django import forms
from .models import CourseSelection, UniversityPriority, AssessmentResult, Subject, CourseDuration


class CourseFilterForm(forms.Form):
    duration = forms.ModelChoiceField(queryset=CourseDuration.objects.all(), required=False,
                                     empty_label="Любой срок", label="Срок курса")
    school = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={"hidden": True}))
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.filter(is_olympiad=False), required=False, empty_label="Все предметы"
    )
    q = forms.CharField(required=False, label="Поиск", widget=forms.TextInput(attrs={
        "placeholder": "Название курса…"
    }))


class CourseSelectionForm(forms.ModelForm):
    class Meta:
        model = CourseSelection
        fields = ["motivation", "need_tutor"]
        widgets = {
            "motivation": forms.Textarea(attrs={"rows": 6, "placeholder": "Почему ты выбрал этот курс?"}),
            'need_tutor': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class UniversityPriorityForm(forms.ModelForm):
    subjects = forms.ModelMultipleChoiceField(
        label="Предметы для специальности",
        queryset=Subject.objects.all(),
        required=False,
        widget=forms.SelectMultiple()
    )

    class Meta:
        model = UniversityPriority
        fields = [
            "university",
            "city",
            "specialty",
            "is_targeted",
            "subjects",
            "priority",
            "notes",
        ]
        widgets = {
            "priority": forms.Select(choices=[(i, str(i)) for i in range(1, 6)]),
            "notes": forms.Textarea(attrs={"rows": 6, "placeholder": "Почему ты выбрал этот вуз?"}),
            "university": forms.TextInput(attrs={"placeholder": "ВМиП (вуз милых и прикольных)"}),
            "city": forms.TextInput(attrs={"placeholder": "поселок городского типа Шаранга"}),
            "specialty": forms.TextInput(attrs={"placeholder": "Программная инженерия"}),
            "is_targeted": forms.CheckboxInput(),
        }
        labels = {
            "university": "ВУЗ",
            "city": "Город",
            "specialty": "Специальность/направление",
            "is_targeted": "Целевое обучение",
            "priority": "Приоритет",
            "notes": "Заметка",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["subjects"].queryset = Subject.objects.all().order_by("name")

    def clean(self):
        cleaned = super().clean()
        user = self.user
        pr = cleaned.get("priority")
        uni = cleaned.get("university")
        spec = cleaned.get("specialty")

        if user is not None and pr is not None:
            qs = UniversityPriority.objects.filter(user=user, priority=pr)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists() and not qs.filter(university=uni, specialty=spec).exists():
                self.add_error("priority", "Этот приоритет уже занят другой записью.")

        if user is not None and uni and spec:
            exists_qs = UniversityPriority.objects.filter(
                user=user,
                university=uni,
                specialty=spec,
            )
            if self.instance and self.instance.pk:
                exists_qs = exists_qs.exclude(pk=self.instance.pk)
            if exists_qs.exists():
                self.add_error(
                    "specialty",
                    "Это направление в этом вузе уже есть в твоём списке.",
                )

        return cleaned


class AssessmentResultForm(forms.ModelForm):
    class Meta:
        model = AssessmentResult
        fields = ["kind", "subject", "title", "date", "score", "max_score", "place", "notes", "attachment"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"})
        }


class PreparationMethodsForm(forms.Form):
    not_started = forms.BooleanField(required=False, label="Не начал готовиться к этому предмету")
    independently = forms.BooleanField(required=False, label="Готовлюсь самостоятельно")
    with_tutor_or_school = forms.BooleanField(required=False, label="Готовлюсь с репетитором / в школе")

    def __init__(self, *args, has_courses=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_courses = has_courses
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-check-input"
        if has_courses:
            self.fields["not_started"].widget = forms.HiddenInput()

    def clean(self):
        data = super().clean()
        if self.has_courses and data.get("not_started"):
            self.add_error("not_started", "У тебя выбран курс: «Не начал» недоступен.")
        if data.get("not_started") and (data.get("independently") or data.get("with_tutor_or_school")):
            raise forms.ValidationError("«Не начал» нельзя сочетать с другими способами подготовки.")
        return data


class PreparationAddForm(forms.Form):
    direction = forms.ChoiceField(label="Предмет ЕГЭ")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["direction"].choices = [
            (str(subject.pk), subject.name) for subject in Subject.objects.filter(is_olympiad=False)
        ]
