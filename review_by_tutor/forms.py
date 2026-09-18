from django import forms

from core.models import MotivationLetter
from documents.models import Document
from my_study.models import Subject
from review_by_tutor.models import Interview, TestAssignment, InterviewResult
from scholar_form.models import UserInfo, UserPersonalData, ScholarVideo


class SelectionStepUpdateForm(forms.ModelForm):
    class Meta:
        model = UserInfo
        fields = ["selection_step"]
        widgets = {
            "selection_step": forms.Select(attrs={"class": "form-select"}),
        }


class StatusChangeForm(forms.ModelForm):
    class Meta:
        model = UserInfo
        fields = ["status", "internal_study_profile"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
            "internal_study_profile": forms.Select(attrs={"class": "form-select"}),
        }


class ProfileChangeForm(forms.ModelForm):
    class Meta:
        model = UserInfo
        fields = ["internal_study_profile"]
        widgets = {
            "internal_study_profile": forms.Select(attrs={"class": "form-select"}),
        }


class MotivationLetterStaffForm(forms.ModelForm):
    class Meta:
        model = MotivationLetter
        fields = ["admin_score", "admin_rating",]
        widgets = {
            "admin_rating": forms.Textarea(attrs={
                "rows": 6,
                "class": "form-control",
                "placeholder": "Ваши комментарии/оценка"
            }),
        }
        labels = {
            "admin_score": "Оценка администратора",
            "admin_rating": "Внутрення заметка по мотивационному письму",
        }


class UserInfoStaffForm(forms.ModelForm):
    planned_exams = forms.ModelMultipleChoiceField(
        queryset=Subject.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select"}),
        label="Планируемые экзамены",
    )

    class Meta:
        model = UserInfo
        exclude = ("user", "created_at", "updated_at", "avatar", "email")

        widgets = {
            "mother": forms.Textarea(attrs={"rows": 2}),
            "father": forms.Textarea(attrs={"rows": 2}),
            "legal_guardian": forms.Textarea(attrs={"rows": 2}),
            "address": forms.Textarea(attrs={"rows": 2}),
            "school_address": forms.Textarea(attrs={"rows": 2}),
            "subject_grades": forms.Textarea(attrs={"rows": 3}),
            "olympiad_plans": forms.Textarea(attrs={"rows": 3}),
            "admission_path": forms.Textarea(attrs={"rows": 2}),
            "target_universities": forms.Textarea(attrs={"rows": 2}),
            "specializations": forms.Textarea(attrs={"rows": 2}),
            "siblings_info": forms.Textarea(attrs={"rows": 2}),
            "other_factors": forms.Textarea(attrs={"rows": 3}),
            "achievements": forms.Textarea(attrs={"rows": 3}),
            "preparation_plan": forms.Textarea(attrs={"rows": 3}),
            "foundation_help": forms.Textarea(attrs={"rows": 2}),
            "heard_about_program": forms.Textarea(attrs={"rows": 2}),
            "tutor_summary": forms.Textarea(attrs={"rows": 4}),
            "planned_exams": forms.SelectMultiple(attrs={
                "class": "form-select js-tomselect",
                "placeholder": "Начни вводить предмет…",
            }),
            "life_situation_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def save(self, commit=True):
        profile = super().save(commit=False)

        user = profile.user
        changed = False

        if "first_name" in self.changed_data and hasattr(user, "first_name"):
            user.first_name = profile.first_name or ""
            changed = True

        if "last_name" in self.changed_data and hasattr(user, "last_name"):
            user.last_name = profile.last_name or ""
            changed = True

        if commit:
            profile.save()
            if changed:
                user.save(update_fields=["first_name", "last_name"])

            self.save_m2m()

        return profile

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.required = False

        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs["class"] = (w.attrs.get("class", "") + " form-check-input").strip()
            else:
                w.attrs["class"] = (w.attrs.get("class", "") + " form-control").strip()

            if isinstance(w, forms.Textarea) and "rows" not in w.attrs:
                w.attrs["rows"] = 2


class ScholarVideoStaffForm(forms.ModelForm):
    class Meta:
        model = ScholarVideo
        fields = [
            "review",
            "score",
            "transcript_text",
            "online_school_prior_experience",
            "online_school_observations",
            "online_school_selected_courses",
            "online_school_choice_reason",
            "online_school_extra_help",
            "online_school_used_materials",
            "online_school_interview_questions",
            "schedule_school_day",
            "schedule_homework_time",
            "schedule_activities_time",
            "schedule_exam_prep_time",
            "schedule_rest_time",
            "schedule_weekend_day",
            "schedule_realistic_assessment",
            "schedule_extra_help",
            "schedule_used_materials",
            "schedule_interview_questions",
        ]
        widgets = {
            "review": forms.Textarea(attrs={
                "rows": 8,
                "class": "form-control",
                "placeholder": "Фидбэк/отзыв куратора по видеовизитке"
            }),
            "score": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 0,
                "step": 1,
                "placeholder": "Баллы (целое число)"
            }),
            "transcript_text": forms.Textarea(attrs={"rows": 8, "class": "form-control"}),
            "online_school_prior_experience": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "online_school_observations": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
            "online_school_selected_courses": forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
            "online_school_choice_reason": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "online_school_extra_help": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "online_school_used_materials": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "online_school_interview_questions": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "schedule_school_day": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "schedule_homework_time": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "schedule_activities_time": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "schedule_exam_prep_time": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "schedule_rest_time": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "schedule_weekend_day": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "schedule_realistic_assessment": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "schedule_extra_help": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "schedule_used_materials": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "schedule_interview_questions": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }
        labels = {
            "review": "Отзыв",
            "score": "Оценка в баллах",
            "transcript_text": "Транскрипция видеовизитки",
            "online_school_prior_experience": "Выбор онлайн-школ: занимался ли раньше и где",
            "online_school_observations": "Выбор онлайн-школ: что получилось, что было удобно, что не получилось",
            "online_school_selected_courses": "Выбор онлайн-школ: какие курсы выбраны на следующий год",
            "online_school_choice_reason": "Выбор онлайн-школ: обоснование выбора",
            "online_school_extra_help": "Выбор онлайн-школ: нужна ли дополнительная помощь",
            "online_school_used_materials": "Выбор онлайн-школ: опирался ли на предоставленные материалы",
            "online_school_interview_questions": "Выбор онлайн-школ: вопросы для обсуждения на собеседовании",
            "schedule_school_day": "Планирование: как выглядит обычный школьный день",
            "schedule_homework_time": "Планирование: сколько времени уходит на домашнюю работу",
            "schedule_activities_time": "Планирование: сколько времени уходит на кружки, спорт и допактивности",
            "schedule_exam_prep_time": "Планирование: сколько времени уходит на ЕГЭ и олимпиады",
            "schedule_rest_time": "Планирование: сколько времени уходит на отдых",
            "schedule_weekend_day": "Планирование: как выглядит обычный выходной",
            "schedule_realistic_assessment": "Планирование: реалистичность графика",
            "schedule_extra_help": "Планирование: нужна ли дополнительная помощь",
            "schedule_used_materials": "Планирование: опирался ли на предоставленные материалы",
            "schedule_interview_questions": "Планирование: вопросы для обсуждения на собеседовании",
        }


class DocumentModerationForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["status", "only_staff_comment"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
            "only_staff_comment": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
        }
        labels = {
            "status": "Статус",
            "only_staff_comment": "Комментарий только для сотрудников"
        }


class DocumentAttachForm(forms.Form):
    MODE_CHOICES = (("set", "Заменить список"), ("add", "Добавить к списку"))
    documents_to_attach = forms.ModelMultipleChoiceField(
        queryset=Document.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Прикрепить к этому документу",
    )
    mode = forms.ChoiceField(choices=MODE_CHOICES, initial="set", widget=forms.RadioSelect, label="Режим")
    mirror = forms.BooleanField(required=False, initial=True, label="Синхронизировать в обе стороны")

    def __init__(self, *args, user=None, exclude_document=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Document.objects.filter(user=user, is_deleted=False)
        if exclude_document:
            qs = qs.exclude(pk=exclude_document.pk)
        self.fields["documents_to_attach"].queryset = qs.order_by("-uploaded_at")


class DocumentStaffUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["file", "caption", "status", "only_staff_comment"]
        widgets = {
            "caption": forms.TextInput(attrs={"class": "form-control", "placeholder": "Название/подпись документа"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "only_staff_comment": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }
        labels = {
            "file": "Файл",
            "caption": "Подпись",
            "status": "Статус",
            "only_staff_comment": "Комментарий только для сотрудников",
        }

    file = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "form-control"}))


class UserPersonalDataStaffForm(forms.ModelForm):
    class Meta:
        model = UserPersonalData
        fields = [
            "last_name", "first_name", "middle_name",
            "passport_series", "passport_number", "passport_issued_at",
            "passport_issued_by", "passport_department_code", "registration_address",
            "phone", "email", "snils",
            "bank_name", "bank_account", "bank_bik", "bank_correspondent_account",
        ]
        widgets = {
            "passport_issued_at": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "registration_address": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
            field.widget.attrs["class"] = "form-control"


class DocumentStatusForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select form-select-sm auto-submit"}),
        }
        labels = {"status": "Статус"}


class DocumentCommentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["only_staff_comment"]
        widgets = {
            "only_staff_comment": forms.Textarea(attrs={
                "rows": 2,
                "class": "form-control form-control-sm",
                "placeholder": "Внутренний комментарий",
            }),
        }
        labels = {"only_staff_comment": "Комментарий (только для сотрудников)"}


class InterviewForm(forms.ModelForm):
    filled_template = forms.FileField(
        required=False,
        label="Заполненный шаблон интервью",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx"}),
    )

    class Meta:
        model = Interview
        fields = ["notes", "video", "video_yandex_disk_url"]
        widgets = {
            "video_yandex_disk_url": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "disk:/Собеседования/2026/video.mp4 или https://disk.yandex.ru/...",
                }
            ),
        }


class TestAssignmentCreateForm(forms.ModelForm):
    class Meta:
        model = TestAssignment
        fields = ("template", "user", "title", "instructions", "due_at", "status")
        widgets = {
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "instructions": forms.Textarea(attrs={"rows": 3}),
        }


class TestAssignmentEditForm(forms.ModelForm):
    class Meta:
        model = TestAssignment
        fields = ("title", "instructions", "due_at", "status")


class TestResultForm(forms.ModelForm):
    class Meta:
        model = TestAssignment
        fields = (
            "numeric_grade",
            "numeric_percentile",
            "verbal_grade",
            "verbal_percentile",
            "logical_grade",
            "logical_percentile",
            "result_text",
            "passed",
        )
        widgets = {
            "result_text": forms.Textarea(attrs={"rows": 4}),
            "numeric_percentile": forms.NumberInput(attrs={"min": "1", "max": "99", "step": "1"}),
            "verbal_percentile": forms.NumberInput(attrs={"min": "1", "max": "99", "step": "1"}),
            "logical_percentile": forms.NumberInput(attrs={"min": "1", "max": "99", "step": "1"}),
        }

class LetterRevisionForm(forms.Form):
    revision_comment = forms.CharField(
        label="Комментарий для соискателя",
        widget=forms.Textarea(attrs={"rows": 4}),
        required=True
    )


from django import forms
from core.models import MotivationLetterRubricReview

class LetterDeadlineForm(forms.ModelForm):
    class Meta:
        model = MotivationLetter
        fields = ("deadline_at",)


class ScholarVideoDeadlineForm(forms.ModelForm):
    deadline_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
        label="Дедлайн",
        help_text="Оставьте пустым, чтобы не задавать дедлайн.",
    )

    class Meta:
        model = ScholarVideo
        fields = ["deadline_at"]

    def clean_deadline_at(self):
        return self.cleaned_data.get("deadline_at") or None


class ScholarVideoYandexPublicLinkForm(forms.Form):
    yandex_public_url = forms.URLField(
        label="Публичная ссылка Яндекс Диска",
        required=True,
        widget=forms.URLInput(attrs={
            "class": "form-control",
            "placeholder": "https://disk.yandex.ru/i/...",
        }),
        help_text="Укажите публичную ссылку на видеофайл или папку с одним видео.",
    )


class MotivationLetterRubricReviewStaffForm(forms.ModelForm):
    class Meta:
        model = MotivationLetterRubricReview

        fields = [
            # meta
            "total_score",
            "char_count",
            "word_count",

            # content scores
            "specialty_choice_score",
            "university_choice_score",
            "current_preparation_score",
            "admission_trajectory_score",
            "next_year_preparation_score",
            "higher_education_value_score",
            "support_criticality_score",

            # rhetoric penalties
            "composition_penalty",
            "style_penalty",

            # literacy penalties
            "orthography_penalty",
            "syntax_penalty",

            # flags
            "is_too_short",
            "score_capped_for_short_length",
            "suspected_ai_generated",
            "returned_for_revision",

            # comment
            "reviewer_comment",

            # extractions
            "family",
            "hobbies",
            "achievements",
            "traits",
            "school_teachers",
            "prep_subjects",
            "specialty",
            "preferred_universities",
            "relocation",
            "olympiads",
            "motivation",
            "help_criticality",
            "extra",

            # explanation
            "justification",
        ]

        widgets = {
            "reviewer_comment": forms.Textarea(attrs={"rows": 4}),
            "justification": forms.Textarea(attrs={"rows": 6}),

            "family": forms.Textarea(attrs={"rows": 2}),
            "hobbies": forms.Textarea(attrs={"rows": 2}),
            "achievements": forms.Textarea(attrs={"rows": 2}),
            "traits": forms.Textarea(attrs={"rows": 2}),
            "school_teachers": forms.Textarea(attrs={"rows": 2}),
            "prep_subjects": forms.Textarea(attrs={"rows": 2}),
            "specialty": forms.Textarea(attrs={"rows": 2}),
            "preferred_universities": forms.Textarea(attrs={"rows": 2}),
            "relocation": forms.Textarea(attrs={"rows": 2}),
            "olympiads": forms.Textarea(attrs={"rows": 2}),
            "motivation": forms.Textarea(attrs={"rows": 2}),
            "help_criticality": forms.Textarea(attrs={"rows": 2}),
            "extra": forms.Textarea(attrs={"rows": 2}),
        }


class InterviewResultForm(forms.ModelForm):
    class Meta:
        model = InterviewResult
        exclude = ("created_at", "updated_at", "interview", "status")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            widget = field.widget
            classes = widget.attrs.get("class", "")
            widget.attrs["class"] = (classes + " form-control").strip()

            if isinstance(widget, forms.Textarea) and "rows" not in widget.attrs:
                widget.attrs["rows"] = 1



class TestRevisionForm(forms.ModelForm):
    class Meta:
        model = TestAssignment
        fields = ["revision_comment"]
        widgets = {
            "revision_comment": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_revision_comment(self):
        txt = (self.cleaned_data.get("revision_comment") or "").strip()
        if not txt:
            raise forms.ValidationError("Нужно написать комментарий, что именно дописать.")
        return txt
