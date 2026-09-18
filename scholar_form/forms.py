from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.dispatch import Signal
from django.forms import HiddenInput
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from formtools.wizard.views import SessionWizardView

from my_study.models import Subject
from .models import UserInfo, ScholarVideo, UserPersonalData


def _sync_user_from_userinfo(userinfo: UserInfo):
    user = getattr(userinfo, "user", None)
    if not user:
        return
    updated_fields = []

    if userinfo.first_name and user.first_name != userinfo.first_name:
        user.first_name = userinfo.first_name
        updated_fields.append("first_name")

    if userinfo.last_name and user.last_name != userinfo.last_name:
        user.last_name = userinfo.last_name
        updated_fields.append("last_name")

    if userinfo.email and user.email != userinfo.email:
        user.email = userinfo.email
        updated_fields.append("email")

    if updated_fields:
        user.save(update_fields=updated_fields)


wizard_done = Signal()


class PersonalForm(forms.ModelForm):
    birth_date = forms.DateField(
        widget=forms.DateInput(
            attrs={'type': 'date'},
            format='%Y-%m-%d',
        ),
        input_formats=['%Y-%m-%d'],
        label='Дата рождения',
        required=True
    )

    vk = forms.CharField(
        label="Ссылка на профиль ВКонтакте",
        widget=forms.TextInput(attrs={
            "caption": "ВАЖНО: ссылка должна быть в формате https://vk.com/id000000000. Чтобы получить такую ссылку, можно конвертировать её через https://regvk.com/"
        })
    )

    class Meta:
        model = UserInfo
        fields = [
            'last_name', 'first_name', 'middle_name', 'gender', 'birth_date', 'vk', 'region', 'city', 'address'
        ]
        widgets = {
            'last_name': forms.TextInput(attrs={'placeholder': 'Иванов'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'Иван'}),
            'middle_name': forms.TextInput(attrs={'placeholder': 'Иванович'}),
            'gender': forms.Select(
                attrs={'class': 'form-control'},
                choices=[('', '— Выберите пол —')] + UserInfo.GENDERS
            ),
            'region': forms.TextInput(attrs={'placeholder': 'Московская область'}),
            'city': forms.TextInput(attrs={'placeholder': 'поселок городского типа Шаранга'}),
            'address': forms.TextInput(attrs={'placeholder': 'ул. Ленина, д. 1, кв. 2'}),
        }
        help_texts = {
            'middle_name': 'при наличии'
        }


class EducationForm(forms.ModelForm):
    class_teacher = forms.CharField(
        widget=forms.TextInput(
            attrs={'placeholder': 'Петрова Мария Ивановна, +7 (999) 123-45-67, teacher@example.com'}
        ),
        label='Классный руководитель',
        required=True,
        help_text="ФИО, телефон, email"
    )

    subject_grades = forms.CharField(
        widget=forms.Textarea(attrs={'placeholder': 'Русский язык — 5, математика — 4 …', 'caption': 'Найди среднее арифметическое 2 итоговых оценок, выставленных за последние 2 отчетных периода (четверть/полугодие/триместр) по каждому профильному предмету. Например: по физике за прошлую четверть 5, за позапрошлую 4. Среднее: 4,5.'}),
        help_text="Все предметы, которые сдаешь на ЕГЭ",
        required=True,
        label='Средний балл по профильным предметам за последние 2 отчетных периода'
    )

    planned_exams = forms.ModelMultipleChoiceField(
        label="Планируемые экзамены",
        queryset=Subject.objects.all(),
        required=False,
        widget=forms.SelectMultiple()
    )

    class Meta:
        model = UserInfo
        fields = [
            'school_name',
            'school_address',
            'class_teacher',
            'next_year_class_digit',
            'class_profile',
            'planned_exams',
            'subject_grades',

            'avg_grade_last_period',
        ]

        widgets = {
            'school_name': forms.TextInput(attrs={'placeholder': 'МБОУ СОШ №1'}),
            'school_address': forms.TextInput(attrs={'placeholder': 'г. Москва, ул. Школьная, 5'}),
            'class_profile': forms.TextInput(attrs={'placeholder': 'Физико-математический'}),
            'subject_grades': forms.Textarea(attrs={'placeholder': 'Математика — 5, Физика — 4'}),

            'avg_grade_last_period': forms.NumberInput(attrs={
                'step': '0.01',
                'min': '1',
                'max': '10',
                'placeholder': '4.3',
                'caption': 'Найди среднее арифметическое итоговых оценок по всем предметам за последний отчетный период (четверть/полугодие/триместр).'
            }),
        }

        help_texts = {
            'avg_grade_last_period': 'Оценки по всем предметам',
        }


class AdmissionForm(forms.ModelForm):
    class Meta:
        model = UserInfo
        fields = [
            'olympiad_plans', 'admission_path', 'target_universities', 'specializations'
        ]
        widgets = {
            'olympiad_plans': forms.Textarea(attrs={
                'placeholder': 'Планирую участвовать во ВсОШ по математике, Всесибе по биологии и химии, Высшей пробе по химии'}),
            'admission_path': forms.Textarea(attrs={
                'placeholder': 'Буду писать перечневые олимпиады, но рассчитываю в основном на поступление по ЕГЭ. У меня есть льгота, планирую взять целевое.'}),
            'target_universities': forms.Textarea(
                attrs={'placeholder': '1. МГУ, Москва\n2. СПбПУ, Санкт-Петербург\n3. КубГУ, Краснодар…',
                       "caption": 'Мы не требуем от тебя окончательного решения уже сейчас. Укажи те вузы, о которых ты слышал(-а), что они выпускают специалистов твоего направления, и в которых ты хотел(-а) бы учиться.'}),
            'specializations': forms.Textarea(attrs={'placeholder': 'Прикладная математика, инженерия',
                                                     'caption': 'Мы не требуем от тебя окончательного решения уже сейчас. Но наверняка у тебя есть примерный '
                                                                'перечень специальностей, о которых ты задумывался(-ась). Укажи в заявке те направления, '
                                                                'которые тебе были бы интересны.', }),
        }

        help_texts = {
            'target_universities': 'не более 5',
        }


class FamilyForm(forms.ModelForm):
    class Meta:
        model = UserInfo
        fields = [
            'mother',
            'father',
            'legal_guardian',
            'siblings_count',
            'siblings_info',
            'family_size',
            'income_per_member',
            'is_low_income',
            'receives_subsidy',

            'family_material_status',

            'other_factors',
            'has_pc_with_internet'
        ]

        widgets = {
            'mother': forms.Textarea(
                attrs={'placeholder': 'Иванова Наталья Петровна, врач, ГКБ №1, mama@example.com, +73000000000'}),
            'father': forms.Textarea(
                attrs={'placeholder': 'Иванов Пётр Сергеевич, инженер, Газпром, papa@example.com, +73000000000'}),
            'legal_guardian': forms.Textarea(attrs={'placeholder': 'Не заполняется, если не актуально'}),
            'siblings_count': forms.NumberInput(attrs={'placeholder': '1'}),
            'siblings_info': forms.Textarea(attrs={
                'placeholder': 'Брат — Иван, 20 лет, студент 3 курса\nСестра — Алина, 12 лет, учится в 5 классе'}),
            'family_size': forms.NumberInput(attrs={'placeholder': '4'}),
            'income_per_member': forms.TextInput(attrs={'placeholder': '15 000',
                                                        'caption': 'Сложи годовой доход «на руки» каждого родителя, раздели на 12 и затем на число членов семьи.', }),
            'is_low_income': forms.TextInput(attrs={'placeholder': 'Да / Нет'}),
            'receives_subsidy': forms.TextInput(attrs={'placeholder': 'Да, пособие на ребенка'}),

            'family_material_status': forms.Select(attrs={
                'class': 'form-control'
            }),

            'other_factors': forms.Textarea(attrs={'placeholder': 'Семья снимает жилье, значительная часть бюджета уходит на лекарства бабушки и др.'}),
            'has_pc_with_internet': forms.TextInput(attrs={'placeholder': 'Да / Нет'}),
        }

        help_texts = {
            'mother': "ФИО, место работы, должность, контакт",
            'father': "ФИО, место работы, должность, контакт",
            'legal_guardian': "ФИО, место работы, должность, контакт",
            'receives_subsidy': 'Если да, указать основание',
            'other_factors': 'Если нет, поставь прочерк'
        }


class AdditionalForm(forms.ModelForm):
    agree_processing = forms.BooleanField(label="Даю согласие на обработку персональных данных (ссылка: https://disk.yandex.ru/d/kme9vXodYjntrA)")
    agree_documents = forms.BooleanField(label="В случае утверждения участия в программе обязуюсь предоставить в Фонд документы, подтверждающие предоставленные данные")
    agree_program_conditions = forms.BooleanField(
        label="Ознакомился(-ась) с условиями Благотворительной программы “Поддержи таланты” (ссылка: https://disk.yandex.ru/d/ESiT-bmIM6r6dQ)"
    )

    agree_privacy_policy = forms.BooleanField(
        label="Согласен(-на) с Политикой конфиденциальности (ссылка: https://disk.yandex.ru/d/I2-TWTBEYwWdXw)"
    )

    class Meta:
        model = UserInfo
        fields = [
            'achievements', 'preparation_plan', 'foundation_help',
            'heard_about_program', 'willing_to_participate',
            'agree_program_conditions', 'agree_privacy_policy',
            'agree_processing', 'agree_documents',
        ]
        widgets = {
            'achievements': forms.Textarea(attrs={'placeholder': 'Призер муниципального этапа ВсОШ по физике, 80 верифицированных часов волонтерства на добро.рф, диплом 2 степени на областном фестивале исполнителей на русских народных инструментах, золотая медаль на городских соревнованиях по баскетболу'}),
            'preparation_plan': forms.Textarea(attrs={'placeholder': 'Хожу на дополнительные занятия в школе, занимаюсь с репетитором, смотрю вебинары и пр'}),
            'foundation_help': forms.Textarea(attrs={'placeholder': 'Курсы подготовки к ЕГЭ, поддержка во время приемной кампании, материальная поддержка для поездок на перечневые олимпиады и др.'}),
            'heard_about_program': forms.Textarea(attrs={'placeholder': 'Увидел(-а) пост в канале онлайн-школы “Название школы”/ в школу приезжал волонтер с презентацией/ увидел(-а) рекламу/ свой вариант'}),
            'willing_to_participate': forms.TextInput(attrs={'placeholder': 'Да / Нет'}),
        }
        help_texts = {
            'heard_about_program': 'Пожалуйста, напиши развернуто'
        }


FORMS = [
    ("step1", PersonalForm),
    ("step2", EducationForm),
    ("step3", AdmissionForm),
    ("step4", FamilyForm),
    ("step5", AdditionalForm),
]

TEMPLATES = {
    "step1": "step1.html",
    "step2": "step2.html",
    "step3": "step3.html",
    "step4": "step4.html",
    "step5": "step5.html",
}


class ApplicationWizard(SessionWizardView):
    def _get_model_fields(self):
        normal = set()
        m2m = set()
        for f in UserInfo._meta.get_fields():
            if f.auto_created and not f.concrete:
                continue
            if isinstance(f, models.ManyToManyField):
                m2m.add(f.name)
            elif getattr(f, "attname", None):
                normal.add(f.name)
        return normal, m2m

    def get_template_names(self):
        return [TEMPLATES[self.steps.current]]

    def get_form_instance(self, step):
        if not hasattr(self, 'user_info_instance'):
            try:
                self.user_info_instance = UserInfo.objects.get(user=self.request.user)
            except UserInfo.DoesNotExist:
                self.user_info_instance = UserInfo(user=self.request.user)
        return self.user_info_instance

    def get_form(self, step=None, data=None, files=None):
        form = super().get_form(step, data, files)

        instance = self.get_form_instance(step or self.steps.current)

        locked = getattr(instance, "form_status", "draft") in {"submitted", "clarification", "approved", "rejected"}

        if locked:
            for name, field in form.fields.items():
                if isinstance(field.widget, HiddenInput):
                    continue
                field.disabled = True
                field.required = False
                if hasattr(field.widget, "attrs"):
                    field.widget.attrs.pop("required", None)
            return form

        required_false_list = ['legal_guardian', 'vk', 'middle_name', 'class_profile']
        for name, field in form.fields.items():
            if name in required_false_list:
                field.required = False
                if hasattr(field.widget, 'attrs'):
                    field.widget.attrs.pop('required', None)
                continue

            field.required = True
            if hasattr(field.widget, 'attrs') and not isinstance(field.widget, HiddenInput):
                field.widget.attrs['required'] = ''

        return form

    def get_form_initial(self, step):
        instance = self.get_form_instance(step)
        initial = {}
        form_class = self.form_list[step]
        model_fields = {f.name for f in UserInfo._meta.get_fields() if getattr(f, 'attname', None)}
        for name in form_class.base_fields.keys():
            if name in model_fields:
                val = getattr(instance, name, None)

                if hasattr(val, "all") and hasattr(val, "values_list"):
                    val = list(val.values_list("pk", flat=True))

                initial[name] = val
        return initial

    @transaction.atomic
    def process_step(self, form):
        instance = self.get_form_instance(self.steps.current)
        normal_fields, m2m_fields = self._get_model_fields()

        m2m_to_set = {}

        for field, value in form.cleaned_data.items():
            if field in normal_fields:
                setattr(instance, field, value)
            elif field in m2m_fields:
                m2m_to_set[field] = value

        instance.save()

        for field, value in m2m_to_set.items():
            getattr(instance, field).set(value or [])

        _sync_user_from_userinfo(instance)
        return super().process_step(form)

    def done(self, form_list, **kwargs):
        if not settings.APPLICATION_SUBMISSIONS_OPEN:
            messages.info(
                self.request,
                "Приём анкет завершён. Черновик сохранён, но отправка недоступна.",
            )
            return self.render(self.get_form(step=self.steps.current))

        instance = self.get_form_instance(None)
        normal_fields, m2m_fields = self._get_model_fields()

        m2m_to_set = {}

        for form in form_list:
            for field, value in form.cleaned_data.items():
                if field in normal_fields:
                    setattr(instance, field, value)
                elif field in m2m_fields:
                    m2m_to_set[field] = value

        instance.form_status = "submitted"
        wizard_done.send(sender=self.__class__, instance=instance, forms=form_list)
        instance.save()

        for field, value in m2m_to_set.items():
            getattr(instance, field).set(value or [])

        _sync_user_from_userinfo(instance)
        return redirect('thank_you')

    def post(self, *args, **kwargs):
        request = self.request
        is_autosave = request.POST.get("_autosave") == "1"

        if is_autosave:
            form = self.get_form(data=request.POST, files=request.FILES, step=self.steps.current)
            for f in form.fields.values():
                f.required = False

            if form.is_valid():
                instance = self.get_form_instance(self.steps.current)
                normal_fields, m2m_fields = self._get_model_fields()

                m2m_to_set = {}
                for field, value in form.cleaned_data.items():
                    if field in normal_fields:
                        setattr(instance, field, value)
                    elif field in m2m_fields:
                        m2m_to_set[field] = value

                instance.save()
                for field, value in m2m_to_set.items():
                    getattr(instance, field).set(value or [])

                _sync_user_from_userinfo(instance)

                from django.http import HttpResponse
                return HttpResponse(status=204)

            return self.render(self.get_form_step_data(form))

        return super().post(*args, **kwargs)

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)

        instance = self.get_form_instance(self.steps.current)
        locked = instance.form_status in {"submitted", "clarification", "approved", "rejected"}

        step = request.GET.get("step")
        if locked and step:
            all_steps = list(self.get_form_list().keys())
            if step in all_steps:
                self.storage.current_step = step
                return self.render(self.get_form(step=step))

        return response

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        context["active"] = "apply"
        return context

    def is_locked(self) -> bool:
        instance = self.get_form_instance(self.steps.current)
        return getattr(instance, "form_status", "draft") in {"submitted", "clarification", "approved", "rejected"}

    def dispatch(self, request, *args, **kwargs):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            instance = self.get_form_instance(getattr(self, "steps", None).current if hasattr(self, "steps") else None)

            locked = getattr(instance, "form_status", "draft") in {"submitted", "clarification", "approved", "rejected"}

            if locked:
                if request.POST.get("_autosave") == "1":
                    return HttpResponseForbidden()

                messages.error(request, "Анкета уже отправлена и не может быть изменена.")
                return redirect("thank_you")

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        instance = self.get_form_instance(self.steps.current)
        context["active"] = "apply"
        context["is_locked"] = getattr(instance, "form_status", "draft") in {"submitted", "clarification", "approved", "rejected"}
        context["application_submission_closed"] = not settings.APPLICATION_SUBMISSIONS_OPEN
        return context


class UserInfoForm(forms.ModelForm):
    class Meta:
        model = UserInfo
        fields = "__all__"
        widgets = {
            # Step 1: Address
            'region': forms.Textarea(attrs={'rows': 2, 'cols': 80}),
            'address': forms.Textarea(attrs={'rows': 2, 'cols': 80}),

            # Step 2: Education
            'school_address': forms.Textarea(attrs={'rows': 2, 'cols': 80}),
            'class_teacher': forms.Textarea(attrs={'rows': 2, 'cols': 80}),
            'planned_exams': forms.CheckboxSelectMultiple(),
            'subject_grades': forms.Textarea(attrs={'rows': 2, 'cols': 80}),

            # Step 3: Admission
            'olympiad_plans': forms.Textarea(attrs={'rows': 3, 'cols': 80}),
            'admission_path': forms.Textarea(attrs={'rows': 3, 'cols': 80}),
            'target_universities': forms.Textarea(attrs={'rows': 2, 'cols': 80}),
            'specializations': forms.Textarea(attrs={'rows': 2, 'cols': 80}),

            # Step 4: Family
            'mother': forms.Textarea(attrs={'rows': 2, 'cols': 80}),
            'father': forms.Textarea(attrs={'rows': 2, 'cols': 80}),
            'legal_guardian': forms.Textarea(attrs={'rows': 2, 'cols': 80}),
            'siblings_info': forms.Textarea(attrs={'rows': 2, 'cols': 80}),
            'other_factors': forms.Textarea(attrs={'rows': 2, 'cols': 80}),

            # Step 5: Additional
            'achievements': forms.Textarea(attrs={'rows': 4, 'cols': 80}),
            'preparation_plan': forms.Textarea(attrs={'rows': 4, 'cols': 80}),
            'foundation_help': forms.Textarea(attrs={'rows': 3, 'cols': 80}),
        }


class UserProfileForm(forms.ModelForm):
    avatar = forms.ImageField(required=False, widget=forms.FileInput(attrs={"accept": "image/*"}))

    class Meta:
        model = UserInfo
        fields = ["avatar"]


class ScholarVideoForm(forms.ModelForm):
    class Meta:
        model = ScholarVideo
        fields = ["file", "schedule_file", "online_school_course"]
        widgets = {
            "online_school_course": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Например: Умскул, ЕГЭ по математике, преподаватель: Иванов Иван Иванович",
                }
            ),
        }

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if not f:
            return f

        allowed_types = {
            "video/mp4",
            "video/webm",
            "video/quicktime",
            "video/x-quicktime",
        }
        allowed_ext = {".mp4", ".webm", ".mov"}
        content_type = getattr(f, "content_type", None) or ""
        ext = Path(getattr(f, "name", "") or "").suffix.lower()

        if content_type not in allowed_types and ext not in allowed_ext:
            raise ValidationError("Видео должно быть в формате MP4, WebM или MOV.")

        max_size = 200 * 1024 * 1024
        if f.size > max_size:
            raise ValidationError("Видео не должно превышать 200 МБ.")

        return f

    def clean_schedule_file(self):
        f = self.cleaned_data.get("schedule_file")
        if not f:
            return f

        allowed_content_types = {
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

        if getattr(f, "content_type", None) not in allowed_content_types:
            raise ValidationError("График должен быть в формате PDF, DOC или DOCX.")

        max_size = 20 * 1024 * 1024
        if f.size > max_size:
            raise ValidationError("Файл графика не должен превышать 20 МБ.")

        return f


class UserPersonalDataForm(forms.ModelForm):
    class Meta:
        model = UserPersonalData
        fields = [
            "last_name",
            "first_name",
            "middle_name",
            "passport_series",
            "passport_number",
            "passport_issued_at",
            "passport_issued_by",
            "passport_department_code",
            "registration_address",
            "bank_name",
            "bank_account",
            "bank_bik",
            "bank_correspondent_account",
            "phone",
            "email",
            "snils",
        ]
        widgets = {
            "passport_issued_at": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "registration_address": forms.Textarea(attrs={"rows": 2}),
        }
