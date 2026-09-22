import mimetypes
import re
from datetime import timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, URLValidator, FileExtensionValidator
from django.db import models
from django.utils import timezone

from my_study.models import Subject


def validate_vk_id_url(value):
    pattern = r'^https://vk\.com/id\d*$'

    if not re.match(pattern, value):
        raise ValidationError(
            "Разрешена только ссылка вида https://vk.com/id123456"
        )


class StaffNote(models.Model):
    target_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="staff_notes")

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="staff_notes_authored")

    text = models.TextField()

    is_favorite = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Заметка стаффа"
        verbose_name_plural = "Заметки стаффа"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_user", "-created_at"]),
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Заметка по {self.target_user_id} | {self.text[:60]}"


class UserInfo(models.Model):
    GENDERS = [('MAN', 'Мужчина'), ('WOMAN', 'Женщина')]
    STATUSES = [('CANDIDATE', 'Кандидат'), ('ALTERNATIVE', 'Альтернативный трек'), ('FINAL STAGE', 'Финалист'), ('SCHOLAR', 'Участник'),
                ('ALUMNUS', 'Выпускник')]

    class SelectionStep(models.TextChoices):
        FORM = "form", "Анкета"
        TEST = "test", "Тестирование способностей"
        ML = "ml", "Мотивационное письмо"
        VIDEO = "video", "Видеовизитка"
        INTERVIEW_PREP = "interview_prep", "Подготовка к собеседованию"
        AFTER_INTERVIEW = "after_interview", "После собеседования"

    selection_step = models.CharField(
        max_length=32,
        choices=SelectionStep.choices,
        default=SelectionStep.FORM,
        db_index=True,
    )

    class FormStatus(models.TextChoices):
        DRAFT = "draft", "Не отправлена"
        SUBMITTED = "submitted", "Отправлена"
        REVISION = "revision", "На дописывание"
        CLARIFICATION = "clarification", "На уточнении"
        APPROVED = "approved", "Принята"
        REJECTED = "rejected", "Отклонена"

    form_status = models.CharField(
        max_length=20,
        choices=FormStatus.choices,
        default=FormStatus.DRAFT,
        verbose_name="Статус анкеты",
        db_index=True,
    )

    revision_comment = models.TextField(
        verbose_name="Комментарий к доработке анкеты",
        blank=True,
        null=True,
    )
    revision_requested_at = models.DateTimeField(
        verbose_name="Запрошена доработка",
        blank=True,
        null=True,
    )

    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True, verbose_name="Аватар")

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, related_name='user_info')
    status = models.CharField(max_length=100, choices=STATUSES, default='CANDIDATE', verbose_name='Статус в программе')

    # Step 1: Personal Info
    last_name = models.CharField(max_length=255, verbose_name="Фамилия", blank=True)
    first_name = models.CharField(max_length=255, verbose_name="Имя", blank=True)
    middle_name = models.CharField(max_length=255, verbose_name="Отчество", blank=True)
    gender = models.CharField(max_length=10, choices=GENDERS, verbose_name="Пол", null=True, blank=True)
    birth_date = models.DateField(verbose_name="Дата рождения", null=True, blank=True)
    phone = models.CharField(max_length=20, verbose_name="Телефон", blank=True)
    email = models.EmailField(verbose_name="Email", blank=True)
    region = models.CharField(max_length=1000, verbose_name="Регион проживания", blank=True)
    city = models.CharField(max_length=1000, verbose_name="Населенный пункт", blank=True)
    address = models.CharField(max_length=1000, verbose_name="Адрес проживания", blank=True)

    # Step 2: Education
    school_name = models.CharField(max_length=255, verbose_name="Название школы", blank=True)
    school_address = models.CharField(max_length=1000, verbose_name="Адрес школы", blank=True)
    class_teacher = models.CharField(max_length=1000, verbose_name="Классный руководитель", blank=True)

    next_year_class_digit = models.IntegerField(verbose_name="Класс в 2026-2027 учебном году", blank=True, null=True,
                                                validators=[
                                                    MinValueValidator(1),
                                                    MaxValueValidator(11)
                                                ])

    class_profile = models.CharField(max_length=255, blank=True, verbose_name="Профиль класса", help_text="при наличии")
    planned_exams = models.ManyToManyField(
        Subject,
        verbose_name="Планируемые экзамены",
        blank=True,
        related_name="planned_by_users"
    )
    subject_grades = models.CharField(max_length=1000, verbose_name="Средний балл по профильным предметам за последние 2 отчетных периода", blank=True)

    # Step 3: Admission Plans
    olympiad_plans = models.CharField(max_length=10000, verbose_name="Планы участия в олимпиадах", blank=True, help_text='Если не планируешь участвовать, поставь прочерк')
    admission_path = models.CharField(max_length=10000, verbose_name="Ты планируешь поступать по ЕГЭ или олимпиадам?", blank=True)
    target_universities = models.CharField(max_length=10000, verbose_name="Приоритетные вузы", blank=True)
    specializations = models.CharField(max_length=10000, verbose_name="Интересующие направления", blank=True)

    # Step 4: Family
    mother = models.CharField(max_length=10000, verbose_name="Мама", blank=True)
    father = models.CharField(max_length=10000, verbose_name="Папа", blank=True)
    legal_guardian = models.CharField(max_length=10000, blank=True, verbose_name="Иной законный представитель")
    siblings_count = models.IntegerField(verbose_name="Количество братьев и сестёр", null=True, blank=True)
    siblings_info = models.CharField(max_length=10000, verbose_name="Информация о братьях и сёстрах", blank=True)
    family_size = models.IntegerField(verbose_name="Общий состав семьи", null=True, blank=True)
    income_per_member = models.CharField(max_length=255, verbose_name="Среднемесячный доход на 1 члена семьи за последние 12 месяцев (руб.)", blank=True)
    is_low_income = models.CharField(max_length=10, verbose_name="Имеет ли семья статус малоимущей?", blank=True)
    receives_subsidy = models.CharField(max_length=255, verbose_name="Получает ли семья субсидии от государства? ", blank=True)
    other_factors = models.CharField(max_length=10000, blank=True, verbose_name="Какие-либо иные обстоятельства, о которых ты хотел(-а) бы сообщить")
    has_pc_with_internet = models.CharField(max_length=1000, verbose_name="Есть ли у тебя компьютер/ноутбук с доступом в интернет?",
                                            blank=True)

    # Step 5: Additional
    vk = models.URLField(max_length=500, verbose_name="Ссылка на вк", blank=True, null=True, validators=[validate_vk_id_url])
    achievements = models.CharField(max_length=10000, verbose_name="Кратко опиши свои достижения за последние два года", blank=True)
    preparation_plan = models.CharField(max_length=10000, verbose_name="Как ты планируешь свою подготовку к поступлению на следующий год?", blank=True)
    foundation_help = models.CharField(max_length=10000, verbose_name="Какую помощь ты хочешь получить от Фонда?", blank=True)
    heard_about_program = models.CharField(max_length=255, verbose_name="Как ты узнал(-а) о программе Фонда?", blank=True)
    willing_to_participate = models.CharField(max_length=10, verbose_name="Готов(-а) ли ты активно принимать участие в программе Фонда?",
                                              blank=True)

    agree_program_conditions = models.BooleanField(
        verbose_name="Ознакомился(-ась) с условиями Благотворительной программы “Поддержи таланты” (ссылка: https://disk.yandex.ru/d/ESiT-bmIM6r6dQ)",
        null=True
    )

    agree_privacy_policy = models.BooleanField(
        verbose_name="Согласен(-на) с Политикой конфиденциальности (ссылка: https://disk.yandex.ru/d/I2-TWTBEYwWdXw)",
        null=True
    )

    agree_processing = models.BooleanField(
        verbose_name="Даю согласие на обработку персональных данных (ссылка: https://disk.yandex.ru/d/kme9vXodYjntrA)",
        null=True
    )

    agree_documents = models.BooleanField(
        verbose_name="В случае утверждения участия в программе обязуюсь предоставить в Фонд документы, подтверждающие предоставленные данные",
        null=True
    )

    after_interview_parents_notified = models.BooleanField(
        default=False,
        verbose_name="Я сообщил(-а) родителям/ законным представителям о том, что принимаю участие в отборе",
    )
    after_interview_documents_ready = models.BooleanField(
        default=False,
        verbose_name="Я готов(-а) предоставить документы для подтверждения анкетных данных, в случае моего прохождения в программу",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата заполнения анкеты")

    tutor_summary = models.TextField(verbose_name="Заметки куратора", blank=True, null=True)

    avg_grade_last_period = models.DecimalField(
        verbose_name="Средний балл успеваемости за последний отчетный период",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Например: 4.57 или 8.92 (зависит от шкалы в школе).",
    )

    class FamilyMaterialStatus(models.TextChoices):
        NOT_ENOUGH_FOOD = "1", "Иногда не хватает денег на необходимые продукты питания"
        FOOD_OK_OTHER_LIMITS = "2", "На еду денег хватает, но на других ежедневных расходах приходится себя ограничивать"
        CLOTHES_HARD = "3", "На ежедневные расходы хватает, но покупка одежды уже представляет трудность"
        TECH_HARD = "4", "На еду и одежду хватает, но покупка техники (телевизор, холодильник и т.п.) представляет трудности"
        CAR_VACATION_CREDIT = "5", "Достаточно обеспечены материально, но для покупки автомобиля и дорогостоящего отпуска пришлось бы залезть в долги"
        CAN_AFFORD = "6", "Материально обеспечены, можем позволить себе дорогостоящий отпуск и покупку автомобиля"
        HARD_TO_ANSWER = "99", "Затрудняюсь ответить"

    family_material_status = models.CharField(
        max_length=2,
        choices=FamilyMaterialStatus.choices,
        blank=True,
        null=True,
        verbose_name="Как бы ты оценил(-а) материальное положение вашей семьи?",
        db_index=True,
    )

    class InternalStudyProfile(models.TextChoices):
        IT = "it", "IT"
        PHYS_MATH = "phys_math", "Физмат"
        MEDIC = "medic", "Врач"
        CHEM_BIO = "chem_bio", "Химбио"
        GEO_ECO = "geo_eco", "География / экология"
        ARCH_DESIGN = "arch_design", "Архитектура / строительство / дизайн"
        HUMANITIES = "humanities", "Гуманитарий"
        OTHER = "other", "Прочее"

    internal_study_profile = models.CharField(
        max_length=32,
        choices=InternalStudyProfile.choices,
        blank=True,
        null=True,
        verbose_name="Учебный профиль (внутренний)",
        help_text="Стафф-поле. Используется в сводке.",
        db_index=True,
    )

    is_large_family = models.BooleanField(
        default=False,
        verbose_name="Многодетность (внутреннее)",
    )
    is_single_parent_family = models.BooleanField(
        default=False,
        verbose_name="Неполная семья (внутреннее)",
    )
    has_candidate_disability = models.BooleanField(
        default=False,
        verbose_name="Инвалидность кандидата (внутреннее)",
    )
    is_orphan_or_under_guardianship = models.BooleanField(
        default=False,
        verbose_name="Сирота / под опекой (внутреннее)",
    )
    has_breadwinner_loss = models.BooleanField(
        default=False,
        verbose_name="Потеря кормильца (внутреннее)",
    )
    has_relative_disability = models.BooleanField(
        default=False,
        verbose_name="Инвалидность близкого (внутреннее)",
    )
    is_parent_pensioner = models.BooleanField(
        default=False,
        verbose_name="Родитель пенсионер (внутреннее)",
    )
    is_parent_in_svo = models.BooleanField(
        default=False,
        verbose_name="Родитель на СВО (внутреннее)",
    )
    has_alumni_sibling = models.BooleanField(
        default=False,
        verbose_name="Сиблинг выпускника (внутреннее)",
    )

    class SettlementType(models.TextChoices):
        BIG_CITY = "big_city", "Крупный город"
        MID_CITY = "mid_city", "Средний город"
        SMALL_SETTLEMENT = "small_settlement", "Малое поселение"

    settlement_type = models.CharField(
        max_length=32,
        choices=SettlementType.choices,
        blank=True,
        null=True,
        verbose_name="Тип населённого пункта (внутреннее)",
        db_index=True,
    )

    life_situation_notes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Особенность жизненной ситуации (внутреннее)",
        help_text="Коротко: что важно учесть при рассмотрении анкеты.",
    )

    @property
    def is_locked(self) -> bool:
        return self.form_status in {
            self.FormStatus.SUBMITTED,
            self.FormStatus.CLARIFICATION,
            self.FormStatus.APPROVED,
            self.FormStatus.REJECTED,
        }

    class Meta:
        verbose_name = "Анкета участника"
        verbose_name_plural = "Анкеты участников"

def video_upload_to(instance, filename):
    return f"videos/visits/{instance.user_id}/{filename}"


def validate_video_size(f):
    max_mb = 200
    if f.size > max_mb * 1024 * 1024:
        raise ValidationError(f"Файл больше {max_mb} МБ.")


def validate_video_ext(f):
    allowed_ext = {".mp4", ".webm", ".mov"}
    name = getattr(f, "name", "") or ""
    ext = Path(name).suffix.lower()
    ctype = getattr(f, "content_type", "") or mimetypes.guess_type(name)[0] or ""
    if ext not in allowed_ext and ctype not in {"video/mp4", "video/webm", "video/quicktime", "video/x-quicktime"}:
        raise ValidationError("Допустимы только MP4, WebM или MOV.")

def default_video_deadline():
    return timezone.now() + timedelta(days=30)


class ScholarVideo(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="scholar_video")
    review = models.TextField(verbose_name="Отзыв", blank=True, null=True)
    score = models.PositiveIntegerField(verbose_name="Оценка в баллах", blank=True, null=True)
    transcript_text = models.TextField(
        blank=True,
        default="",
        verbose_name="Транскрипция видеовизитки",
    )
    transcript_status = models.CharField(
        "Статус транскрибации",
        max_length=20,
        choices=[
            ("PENDING", "Ожидает"),
            ("PROCESSING", "В работе"),
            ("DONE", "Готово"),
            ("FAILED", "Ошибка"),
        ],
        default="PENDING",
    )
    transcript_error = models.TextField("Ошибка транскрибации", blank=True)
    transcript_updated_at = models.DateTimeField(null=True, blank=True)

    schedule_file = models.FileField(
        upload_to="scholar_video_schedules/",
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["pdf", "doc", "docx"])
        ],
        verbose_name="График занятий",
    )

    online_school_course = models.TextField(
        blank=True,
        default="",
        verbose_name="Онлайн-школа и курс",
        help_text="Укажи онлайн-школу и курс в свободной форме",
    )
    online_school_prior_experience = models.TextField(
        blank=True,
        default="",
        verbose_name="Онлайн-школы: предыдущий опыт",
    )
    online_school_observations = models.TextField(
        blank=True,
        default="",
        verbose_name="Онлайн-школы: наблюдения и выводы",
    )
    online_school_selected_courses = models.TextField(
        blank=True,
        default="",
        verbose_name="Онлайн-школы: выбранные курсы",
    )
    online_school_choice_reason = models.TextField(
        blank=True,
        default="",
        verbose_name="Онлайн-школы: обоснование выбора",
    )
    online_school_extra_help = models.TextField(
        blank=True,
        default="",
        verbose_name="Онлайн-школы: нужна ли дополнительная помощь",
    )
    online_school_used_materials = models.TextField(
        blank=True,
        default="",
        verbose_name="Онлайн-школы: опирался ли на предоставленные материалы",
    )
    online_school_interview_questions = models.TextField(
        blank=True,
        default="",
        verbose_name="Онлайн-школы: вопросы для обсуждения на собеседовании",
    )
    schedule_school_day = models.TextField(
        blank=True,
        default="",
        verbose_name="График: обычный школьный день",
    )
    schedule_homework_time = models.TextField(
        blank=True,
        default="",
        verbose_name="График: время на домашнюю работу",
    )
    schedule_activities_time = models.TextField(
        blank=True,
        default="",
        verbose_name="График: время на допактивности, кружки и спорт",
    )
    schedule_exam_prep_time = models.TextField(
        blank=True,
        default="",
        verbose_name="График: время на подготовку к ЕГЭ и олимпиадам",
    )
    schedule_rest_time = models.TextField(
        blank=True,
        default="",
        verbose_name="График: время на отдых",
    )
    schedule_weekend_day = models.TextField(
        blank=True,
        default="",
        verbose_name="График: обычный выходной",
    )
    schedule_realistic_assessment = models.TextField(
        blank=True,
        default="",
        verbose_name="График: реалистичность плана",
    )
    schedule_extra_help = models.TextField(
        blank=True,
        default="",
        verbose_name="График: нужна ли дополнительная помощь",
    )
    schedule_used_materials = models.TextField(
        blank=True,
        default="",
        verbose_name="График: опирался ли на предоставленные материалы",
    )
    schedule_interview_questions = models.TextField(
        blank=True,
        default="",
        verbose_name="График: вопросы для обсуждения на собеседовании",
    )

    deadline_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дедлайн сдачи видеовизитки",
        default=None,
        db_index=True,
    )

    file = models.FileField(
        "Видео",
        upload_to=video_upload_to,
        validators=[validate_video_size, validate_video_ext],
        help_text="MP4/WebM, до 200 МБ",
        blank=True,
        null=True,
    )
    yandex_disk_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        verbose_name="РџСѓС‚СЊ РЅР° РЇРЅРґРµРєСЃ Р”РёСЃРєРµ",
    )
    yandex_disk_uploaded_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Р—Р°РіСЂСѓР¶РµРЅРѕ РЅР° РЇРЅРґРµРєСЃ Р”РёСЃРє",
    )
    yandex_disk_error = models.TextField(
        blank=True,
        default="",
        verbose_name="РћС€РёР±РєР° РІС‹РіСЂСѓР·РєРё РЅР° РЇРЅРґРµРєСЃ Р”РёСЃРє",
    )
    schedule_yandex_disk_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        verbose_name="РџСѓС‚СЊ РіСЂР°С„РёРєР° РЅР° РЇРЅРґРµРєСЃ Р”РёСЃРєРµ",
    )
    schedule_yandex_disk_uploaded_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Р“СЂР°С„РёРє Р·Р°РіСЂСѓР¶РµРЅ РЅР° РЇРЅРґРµРєСЃ Р”РёСЃРє",
    )
    schedule_yandex_disk_error = models.TextField(
        blank=True,
        default="",
        verbose_name="РћС€РёР±РєР° РІС‹РіСЂСѓР·РєРё РіСЂР°С„РёРєР° РЅР° РЇРЅРґРµРєСЃ Р”РёСЃРє",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    notes = GenericRelation(StaffNote, related_query_name="videos")

    class Meta:
        verbose_name = "Видеовизитка"
        verbose_name_plural = "Видеовизитки"

    def __str__(self):
        return f"Видеовизитка {self.user.get_full_name() or self.user.username}"


    @staticmethod
    def _storage_name(remote_path: str, local_field) -> str:
        if remote_path:
            if remote_path.startswith("public:"):
                _, _, remote_value = remote_path.partition("#")
                remote_value = unquote(remote_value).strip("/")
            else:
                remote_value = remote_path.replace("disk:/", "", 1).strip("/")
            if remote_value:
                return PurePosixPath(remote_value).name

        local_name = getattr(local_field, "name", "") or ""
        if local_name:
            return PurePosixPath(local_name).name

        return ""

    @property
    def has_video_file(self) -> bool:
        return bool(self.yandex_disk_path or getattr(self.file, "name", ""))

    @property
    def has_schedule_file(self) -> bool:
        return bool(self.schedule_yandex_disk_path or getattr(self.schedule_file, "name", ""))

    @property
    def video_storage_name(self) -> str:
        return self._storage_name(self.yandex_disk_path, self.file)

    @property
    def schedule_storage_name(self) -> str:
        return self._storage_name(self.schedule_yandex_disk_path, self.schedule_file)


class UserPersonalData(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="personal_data",
    )

    last_name = models.CharField("Фамилия", max_length=150, blank=True)
    first_name = models.CharField("Имя", max_length=150, blank=True)
    middle_name = models.CharField("Отчество", max_length=150, blank=True)

    passport_series = models.CharField("Серия паспорта", max_length=10, blank=True)
    passport_number = models.CharField("Номер паспорта", max_length=20, blank=True)
    passport_issued_at = models.DateField("Дата выдачи", blank=True, null=True)
    passport_issued_by = models.CharField("Кем выдан", max_length=255, blank=True)
    passport_department_code = models.CharField("Код подразделения", max_length=20, blank=True)

    registration_address = models.TextField("Адрес регистрации", blank=True)

    bank_name = models.CharField("Банк", max_length=255, blank=True)
    bank_account = models.CharField("Номер счёта", max_length=34, blank=True)
    bank_bik = models.CharField("БИК", max_length=20, blank=True)
    bank_correspondent_account = models.CharField("Корр. счёт", max_length=34, blank=True)

    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("E-mail", blank=True)

    snils = models.CharField("СНИЛС", max_length=20, blank=True)

    submitted_by_user_at = models.DateTimeField(
        "Заполнено пользователем",
        blank=True,
        null=True,
        editable=False,
    )
    accepted_at = models.DateTimeField(
        "Принято администратором",
        blank=True,
        null=True,
        editable=False,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Персональные данные"
        verbose_name_plural = "Персональные данные"

    def __str__(self):
        return f"Персональные данные {self.user}"


class VideoInstruction(models.Model):
    is_active = models.BooleanField("Показывать плашку", default=True)

    title = models.CharField("Заголовок", max_length=120, default="Инструкция к видеовизитке")
    text = models.TextField("Текст", blank=True, default="Перед записью ознакомься с требованиями.")
    url = models.URLField("Ссылка на инструкцию", validators=[URLValidator()])

    button_text = models.CharField("Текст кнопки", max_length=60, default="Открыть инструкцию")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Инструкция к видеовизитке"
        verbose_name_plural = "Инструкция к видеовизитке"

    def __str__(self):
        return self.title

    @classmethod
    def get_current(cls):
        obj = cls.objects.filter(is_active=True).order_by("-updated_at").first()
        return obj


class InterviewInstruction(models.Model):
    is_active = models.BooleanField("Показывать плашку", default=True)

    title = models.CharField("Заголовок", max_length=120, default="Инструкция к собеседованию")
    text = models.TextField("Текст", blank=True, default="Перед собеседованием ознакомься с инструкцией.")
    url = models.URLField("Ссылка на инструкцию", blank=True, default="", validators=[URLValidator()])

    button_text = models.CharField("Текст кнопки", max_length=60, default="Открыть инструкцию")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Инструкция к собеседованию"
        verbose_name_plural = "Инструкция к собеседованию"

    def __str__(self):
        return self.title

    @classmethod
    def get_current(cls):
        obj = cls.objects.filter(is_active=True).order_by("-updated_at").first()
        return obj
