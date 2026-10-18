import random
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings

from scholar_form.models import StaffNote


MOTIVATION_LETTER_MAX_LENGTH = 20000
DEFAULT_NOTIFICATION_SENDER_NAME = 'Команда фонда «Путёвка в жизнь»'


class TelegramAccount(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_account',
        verbose_name="Пользователь"
    )

    telegram_id = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        verbose_name="Telegram ID"
    )

    username = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Имя пользователя Telegram"
    )

    first_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Имя"
    )

    last_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Фамилия"
    )

    language_code = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        verbose_name="Языковой код"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Последнее обновление"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания"
    )

    activation_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        null=True,
        blank=True,
        verbose_name="Токен активации Telegram",
        help_text="Уникальный токен для активации аккаунта через Telegram."
    )
    telegram_verified = models.BooleanField(
        default=False,
        verbose_name="Активен ли веб-аккаунт",
        help_text="Определяет, активирован ли пользовательский аккаунт на сайте после привязки Telegram."
    )

    class Meta:
        verbose_name = "Аккаунт Telegram"
        verbose_name_plural = "Аккаунты Telegram"
        indexes = [
            models.Index(fields=['telegram_id']),
            models.Index(fields=['activation_token']),
        ]

    def __str__(self):
        return f"{self.user.username}'s Telegram Account ({self.telegram_id if self.telegram_id else 'Не привязан'})"


class RegistrationPersonalData(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True,
                                help_text="Ссылка на созданного пользователя после завершения регистрации.")
    nto_campaign_slug = models.SlugField(max_length=80, blank=True, default="", help_text="Сезон НТО, с которого начата регистрация.")

    email = models.EmailField(unique=True, help_text="Email, введенный пользователем.")
    password = models.CharField(max_length=128, help_text="Хешированный пароль пользователя.")

    email_verification_code = models.UUIDField(
        "Токен для подтверждения email",
        default=uuid.uuid4,
        unique=True,
        editable=False,
        null=True, blank=True,
        db_index=True,
    )

    email_code_sent_at = models.DateTimeField(null=True, blank=True,
                                                help_text="Время истечения срока действия кода email.")

    email_code_expires_at = models.DateTimeField(null=True, blank=True,
                                                 help_text="Время истечения срока действия кода email.")

    email_verified = models.BooleanField(default=False,
                                         help_text="True, если email был успешно подтвержден.")

    telegram_account = models.OneToOneField(TelegramAccount, on_delete=models.SET_NULL, null=True, blank=True,
                                            help_text="Ссылка на связанный TelegramAccount для активации.")

    phone = models.CharField(max_length=20, blank=True, null=True,
                                    help_text="Номер телефона, введенный пользователем (если не из Telegram).")

    phone_verified = models.BooleanField(default=False,
                                         help_text="True, если номер телефона был успешно подтвержден.")

    current_step = models.CharField(max_length=50, default='initial_data',
                                    choices=[
                                        ('initial_data', 'Ввод начальных данных'),
                                        ('email_verification', 'Подтверждение Email'),
                                        ('telegram_connection', 'Подключение Telegram'),
                                        ('phone_verification_needed', 'Требуется подтверждение телефона'),
                                        ('phone_verification_code', 'Ввод кода подтверждения телефона'),
                                        ('finish', 'Завершение регистрации'),
                                    ],
                                    help_text="Текущий шаг в процессе регистрации.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Попытка регистрации"
        verbose_name_plural = "Попытки регистрации"

    def __str__(self):
        return f"Попытка регистрации для {self.email} (Шаг: {self.current_step})"

    def is_email_code_expired(self):
        return self.email_code_expires_at and self.email_code_expires_at < timezone.now()

    def generate_email_code(self):
        self.email_verification_code = uuid.uuid4()
        self.email_code_sent_at = timezone.now()
        self.email_code_expires_at = timezone.now() + timedelta(minutes=15)
        self.save()

class MotivationLetter(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        SUBMITTED = 'submitted', 'Отправлено'
        REVISION = 'revision', 'На дописывании'

    is_done = models.BooleanField(default=False, verbose_name='Мотивационное письмо принято')

    deadline_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дедлайн сдачи мотивационного письма",
        db_index=True,
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='motivation_letter',
        verbose_name="Стипендиат"
    )

    letter_text = models.TextField(
        blank=True,
        max_length=MOTIVATION_LETTER_MAX_LENGTH,
        help_text='Вставьте своё мотивационное письмо сюда',
        verbose_name='Текст мотивационного письма'
    )

    is_favorite = models.BooleanField(
        default=False,
        verbose_name="Избранное письмо",
        db_index=True,
    )

    admin_score = models.PositiveSmallIntegerField(
        verbose_name='Итоговый балл',
        validators=[MinValueValidator(0), MaxValueValidator(70)],
        help_text="Введите значение от 0 до 70",
        blank=True,
        null=True
    )

    admin_rating = models.TextField(
        verbose_name="Оценка администратора",
        null=True,
        blank=True,
    )

    revision_comment = models.TextField(
        null=True, blank=True,
        verbose_name="Комментарий на доработку (видит соискатель)"
    )
    revision_requested_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Отправлено на доработку в",
        db_index=True
    )
    revision_requested_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="motivation_letters_revision_requested",
        verbose_name="Кто отправил на доработку"
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Статус",
        db_index=True
    )
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="Отправлено в", db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    notes = GenericRelation(StaffNote, related_query_name="documents")

    class Meta:
        verbose_name = "Мотивационное письмо"
        verbose_name_plural = "Мотивационные письма"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'submitted_at']),
            models.Index(fields=['created_at']),
        ]

    def clean(self):
        if self.pk:
            original = MotivationLetter.objects.get(pk=self.pk)

            if (
                original.status == self.Status.SUBMITTED
                and self.status == self.Status.SUBMITTED
                and self.letter_text != original.letter_text
            ):
                raise ValidationError("Нельзя изменять текст письма после отправки.")

        if len(self.letter_text or "") > MOTIVATION_LETTER_MAX_LENGTH:
            raise ValidationError({
                "letter_text": (
                    f"Letter text must not exceed {MOTIVATION_LETTER_MAX_LENGTH} characters."
                )
            })

        if self.status == self.Status.SUBMITTED and not self.submitted_at:
            self.submitted_at = timezone.now()

        if self.status == self.Status.SUBMITTED and not (self.letter_text or "").strip():
            raise ValidationError("Нельзя отправить пустое письмо.")

    def save(self, *args, **kwargs):
        if self.status == self.Status.SUBMITTED and self.submitted_at is None:
            self.submitted_at = timezone.now()
            self.is_done = True

        if self.status == self.Status.REVISION:
            self.is_done = False

        super().save(*args, **kwargs)

    def word_count(self) -> int:
        txt = (self.letter_text or "").strip()
        return len([w for w in txt.split() if w])

    def apply_gpt_result(self, *, score: int | None, word_count: int | None,
                         payload_json: dict | None, summary: str | None,
                         flags: dict | None = None, model_name: str | None = None,
                         rubric_version: str | None = None):
        if summary is not None:
            self.gpt_review = summary
        if score is not None:
            self.gpt_score = int(score)
        if word_count is not None:
            self.gpt_word_count = int(word_count)
        if payload_json is not None:
            self.gpt_json = payload_json
        if flags is not None:
            self.gpt_flags = flags
        if model_name is not None:
            self.gpt_model = model_name
        if rubric_version is not None:
            self.gpt_version = rubric_version
        self.gpt_scored_at = timezone.now()

    def send_to_revision(self, *, comment: str, by_user):
        self.status = self.Status.REVISION
        self.revision_comment = comment
        self.revision_requested_at = timezone.now()
        self.revision_requested_by = by_user
        self.is_done = False

    def is_deadline_passed(self) -> bool:
        return bool(self.deadline_at and timezone.now() > self.deadline_at)

    def days_left(self) -> int | None:
        if not self.deadline_at:
            return None
        delta = self.deadline_at.date() - timezone.now().date()
        return max(delta.days, 0)

    def __str__(self):
        return f"Письмо от {self.user.username} - {self.created_at.strftime('%Y-%m-%d')}"


class MotivationLetterRubricReview(models.Model):
    class Topic10WithMaterialsGrade(models.TextChoices):
        FULL_WITH_MATERIALS = "10", "Да, развёрнуто и материалы учтены — 10"
        BRIEF_WITH_MATERIALS = "5", "Да, но кратко/гипотетически, материалы учтены — 5"
        BRIEF_NO_MATERIALS = "2", "Да, но кратко/гипотетически, материалы не учтены — 2"
        NONE = "0", "Нет — 0"

    class Topic10TrajectoryGrade(models.TextChoices):
        FULL_WITH_REASON_AND_MATERIALS = "10", "Да, развёрнуто; есть обоснование; материалы учтены — 10"
        BRIEF_WITH_REASON_AND_MATERIALS = "5", "Да, кратко/гипотетически; есть обоснование; материалы учтены — 5"
        BRIEF_NO_REASON_OR_NO_MATERIALS = "2", "Да, кратко/гипотетически; нет обоснования ИЛИ материалы не учтены — 2"
        NONE = "0", "Нет — 0"

    class Topic10Grade(models.TextChoices):
        FULL = "10", "Да, развёрнуто и по существу — 10"
        BRIEF = "5", "Да, но кратко/гипотетически — 5"
        NONE = "0", "Нет — 0"

    class Penalty02or5(models.TextChoices):
        NONE = "0", "Нет замечаний — 0"
        MINOR = "-2", "Незначительные проблемы — -2"
        MAJOR = "-5", "Серьёзные проблемы — -5"

    letter = models.OneToOneField(
        "MotivationLetter",
        on_delete=models.CASCADE,
        related_name="rubric_review",
        verbose_name="Мотивационное письмо",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата оценки",
    )

    model_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name="Модель ИИ",
    )

    schema_version = models.CharField(
        max_length=32,
        blank=True,
        default="v3.0-2026-04-25",
        verbose_name="Версия рубрики",
    )

    char_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество символов",
        help_text="По новой рубрике важен объём письма в символах",
    )

    word_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Количество слов",
    )

    total_score = models.IntegerField(
        default=0,
        verbose_name="Итоговый балл",
    )

    specialty_choice_score = models.CharField(
        max_length=2,
        choices=Topic10WithMaterialsGrade.choices,
        default=Topic10WithMaterialsGrade.NONE,
        verbose_name="Тема №2: выбор специальности",
    )

    university_choice_score = models.CharField(
        max_length=2,
        choices=Topic10WithMaterialsGrade.choices,
        default=Topic10WithMaterialsGrade.NONE,
        verbose_name="Тема №3: выбор вуза",
    )

    current_preparation_score = models.CharField(
        max_length=2,
        choices=Topic10Grade.choices,
        default=Topic10Grade.NONE,
        verbose_name="Тема №4: текущая подготовка",
    )

    admission_trajectory_score = models.CharField(
        max_length=2,
        choices=Topic10TrajectoryGrade.choices,
        default=Topic10TrajectoryGrade.NONE,
        verbose_name="Тема №5: траектория поступления",
    )

    next_year_preparation_score = models.CharField(
        max_length=2,
        choices=Topic10Grade.choices,
        default=Topic10Grade.NONE,
        verbose_name="Тема №6: подготовка в следующем учебном году",
    )

    higher_education_value_score = models.CharField(
        max_length=2,
        choices=Topic10Grade.choices,
        default=Topic10Grade.NONE,
        verbose_name="Тема №7: значимость высшего образования",
    )

    support_criticality_score = models.CharField(
        max_length=2,
        choices=Topic10Grade.choices,
        default=Topic10Grade.NONE,
        verbose_name="Тема №8: критичность поддержки",
    )

    composition_penalty = models.CharField(
        max_length=2,
        choices=Penalty02or5.choices,
        default=Penalty02or5.NONE,
        verbose_name="Последовательность изложения и композиция",
    )

    style_penalty = models.CharField(
        max_length=2,
        choices=Penalty02or5.choices,
        default=Penalty02or5.NONE,
        verbose_name="Точность и выразительность речи",
    )

    orthography_penalty = models.CharField(
        max_length=2,
        choices=Penalty02or5.choices,
        default=Penalty02or5.NONE,
        verbose_name="Орфография",
    )

    syntax_penalty = models.CharField(
        max_length=2,
        choices=Penalty02or5.choices,
        default=Penalty02or5.NONE,
        verbose_name="Синтаксис",
    )

    is_too_short = models.BooleanField(
        default=False,
        verbose_name="Менее 1000 символов",
    )

    score_capped_for_short_length = models.BooleanField(
        default=False,
        verbose_name="Для текста 1000–1500 символов применён потолок оценки",
        help_text="По критериям максимум 70 для такого объёма не ставится",
    )

    suspected_ai_generated = models.BooleanField(
        default=False,
        verbose_name="Есть признаки написания нейросетью",
    )

    returned_for_revision = models.BooleanField(
        default=False,
        verbose_name="Рекомендовано вернуть на доработку",
    )

    reviewer_comment = models.TextField(
        blank=True,
        default="",
        verbose_name="Комментарий проверяющего",
    )

    family = models.TextField(blank=True, default="", verbose_name="Семья")
    hobbies = models.TextField(blank=True, default="", verbose_name="Увлечения")
    achievements = models.TextField(blank=True, default="", verbose_name="Достижения")
    traits = models.TextField(blank=True, default="", verbose_name="Личные качества")
    school_teachers = models.TextField(blank=True, default="", verbose_name="Школа и преподаватели")
    prep_subjects = models.TextField(blank=True, default="", verbose_name="Предметы для подготовки")
    specialty = models.TextField(blank=True, default="", verbose_name="Специальность")
    preferred_universities = models.TextField(blank=True, default="", verbose_name="Предпочитаемые вузы")
    relocation = models.TextField(blank=True, default="", verbose_name="Возможность переезда")
    olympiads = models.TextField(blank=True, default="", verbose_name="Участие в олимпиадах")
    motivation = models.TextField(blank=True, default="", verbose_name="Мотивация")
    help_criticality = models.TextField(blank=True, default="", verbose_name="Критичность помощи")
    extra = models.TextField(blank=True, default="", verbose_name="Дополнительные данные")

    justification = models.TextField(
        blank=True,
        default="",
        verbose_name="Пояснение эксперта",
    )

    class Meta:
        verbose_name = "Оценка мотивационного письма по рубрике"
        verbose_name_plural = "Оценки мотивационных писем по рубрике"
        indexes = [
            models.Index(fields=["total_score"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["schema_version"]),
            models.Index(fields=["is_too_short"]),
            models.Index(fields=["suspected_ai_generated"]),
        ]

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _calculate_raw_total(self) -> int:
        total = 0

        total += self._to_int(self.specialty_choice_score)
        total += self._to_int(self.university_choice_score)
        total += self._to_int(self.current_preparation_score)
        total += self._to_int(self.admission_trajectory_score)
        total += self._to_int(self.next_year_preparation_score)
        total += self._to_int(self.higher_education_value_score)
        total += self._to_int(self.support_criticality_score)

        total += self._to_int(self.composition_penalty)
        total += self._to_int(self.style_penalty)
        total += self._to_int(self.orthography_penalty)
        total += self._to_int(self.syntax_penalty)

        return total

    def calculate_total_score(self) -> int:
        self.score_capped_for_short_length = False

        if self.suspected_ai_generated:
            return 0

        if self.is_too_short or self.char_count < 1000:
            return 0

        total = self._calculate_raw_total()

        if 1000 <= self.char_count < 1500 and total >= 70:
            self.score_capped_for_short_length = True
            total = 69

        return max(total, 0)

    def save(self, *args, **kwargs):
        self.is_too_short = self.char_count < 1000
        self.total_score = self.calculate_total_score()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Рубрика: письмо #{self.letter_id}, {self.total_score} баллов"


class MotivationLetterInstruction(models.Model):
    title = models.CharField(
        max_length=200,
        default="Инструкция к мотивационному письму",
        verbose_name="Заголовок",
    )
    text = models.TextField(
        blank=True,
        default="Перед написанием мотивационного письма ознакомьтесь с инструкциями.",
        verbose_name="Текст",
    )
    url = models.URLField(
        blank=True,
        default="",
        verbose_name="Ссылка на инструкцию",
    )
    button_text = models.CharField(
        max_length=80,
        default="Открыть инструкцию",
        verbose_name="Текст кнопки",
    )
    file = models.FileField(
        upload_to="motivation/instructions/",
        blank=True,
        null=True,
        verbose_name="Общий файл инструкции",
        help_text="Устаревшее поле. Используется как запасной вариант, если ссылка на инструкцию не задана.",
    )
    is_active = models.BooleanField(default=True, verbose_name="Показывать плашку")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-uploaded_at"]
        verbose_name = "Инструкция к мотивационному письму"
        verbose_name_plural = "Инструкция к мотивационному письму"

    def __str__(self):
        return self.title

    @classmethod
    def get_current(cls):
        return cls.objects.filter(is_active=True).order_by("-updated_at", "-uploaded_at").first()


class AiTask(models.Model):
    class Type(models.TextChoices):
        MOTIVATION_LETTER_REVIEW = "motivation_letter_review", "Motivation letter review"
        INTERVIEW_TRANSCRIPTION = "interview_transcription", "Interview transcription"
        SCHOLAR_VIDEO_TRANSCRIPTION = "scholar_video_transcription", "Scholar video transcription"
        INTERVIEW_RESULT_FILL = "interview_result_fill", "Interview result fill"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        DONE = "DONE", "Done"
        FAILED = "FAILED", "Failed"
        RETRY = "RETRY", "Retry"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_type = models.CharField(max_length=64, choices=Type.choices, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)

    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    source_app = models.CharField(max_length=64, db_index=True)
    source_model = models.CharField(max_length=64, db_index=True)
    source_object_id = models.PositiveIntegerField(db_index=True)
    source_version = models.CharField(max_length=128, blank=True, default="")

    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    locked_by = models.CharField(max_length=128, blank=True, default="")
    locked_until = models.DateTimeField(null=True, blank=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI task"
        verbose_name_plural = "AI tasks"
        indexes = [
            models.Index(fields=["status", "locked_until", "created_at"]),
            models.Index(fields=["source_app", "source_model", "source_object_id", "task_type"]),
        ]

    def __str__(self):
        return f"{self.task_type} #{self.pk} {self.status}"


class TelegramMessageTask(models.Model):
    class BotKind(models.TextChoices):
        USERS = "users", "Users bot"
        ADMIN = "admin", "Admin bot"
        MAIL = "mail", "Mail bot"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        RETRY = "RETRY", "Retry"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot_kind = models.CharField(max_length=16, choices=BotKind.choices, db_index=True)
    chat_id = models.CharField(max_length=64, db_index=True)
    text = models.TextField()
    reply_markup = models.JSONField(null=True, blank=True)
    parse_mode = models.CharField(max_length=16, blank=True, default="HTML")
    disable_web_page_preview = models.BooleanField(default=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    locked_by = models.CharField(max_length=128, blank=True, default="")
    locked_until = models.DateTimeField(null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram message task"
        verbose_name_plural = "Telegram message tasks"
        indexes = [
            models.Index(fields=["status", "locked_until", "created_at"]),
            models.Index(fields=["bot_kind", "chat_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.bot_kind} -> {self.chat_id} {self.status}"


class Notification(models.Model):
    message = models.TextField(verbose_name='Сообщение')

    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='UserNotification',
        related_name='received_notifications',
        verbose_name="Получатели"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='sent_notifications',
        null=True,
        blank=True,
        verbose_name="Отправитель"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Оповещение"
        verbose_name_plural = "Оповещения"

    @property
    def public_sender_name(self) -> str:
        """Return a participant-safe sender label without exposing a login or email."""
        if not self.sender_id:
            return DEFAULT_NOTIFICATION_SENDER_NAME

        name_parts = (self.sender.last_name, self.sender.first_name)
        full_name = " ".join(part.strip() for part in name_parts if part and part.strip())
        return full_name or DEFAULT_NOTIFICATION_SENDER_NAME

    @property
    def contact_email(self) -> str:
        return settings.CONTACT_EMAIL

    @property
    def contact_footer(self) -> str:
        return f"Вопросы? Напишите: {self.contact_email}"

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.sender:
            obj.sender = request.user
        super().save_model(request, obj, form, change)

    def __str__(self):
        return f"Оповещение {self.message[:50] + '...' if len(self.message) > 50 else self.message} от {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class UserNotification(models.Model):
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        verbose_name="Оповещение"
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name="Пользователь"
    )

    tg_sent_at = models.DateTimeField(null=True, blank=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    send_attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    is_seen = models.BooleanField(default=False, verbose_name="Просмотрено")

    seen_at = models.DateTimeField(null=True, blank=True, verbose_name="Время просмотра")

    class Meta:
        unique_together = ('notification', 'recipient')
        verbose_name = "Получатель оповещения"
        verbose_name_plural = "Получатели оповещения"
        ordering = ['-notification__created_at']

    def __str__(self):
        status = "Просмотрено" if self.is_seen else "Не просмотрено"
        return f"Оповещение '{self.notification.message[:20]}...' для {self.recipient.username} - {status}"
