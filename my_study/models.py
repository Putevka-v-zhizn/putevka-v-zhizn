from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

User = settings.AUTH_USER_MODEL


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    is_top = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class School(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Course(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="courses")
    title = models.CharField(max_length=200)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="courses")
    description = models.TextField(blank=True)
    link = models.URLField(blank=True)
    available_to_alternative = models.BooleanField(
        "Доступен альтернативному треку",
        default=False,
    )

    class Meta:
        unique_together = ("school", "title")
        ordering = ["school__name", "title"]

    def __str__(self):
        return f"{self.school.name} — {self.title}"


class CourseSelection(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="course_selections")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="selections")
    motivation = models.TextField(help_text="Почему вы выбрали этот курс/направление?")
    need_tutor = models.BooleanField(default=False, help_text="Нужен куратор")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "course")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} → {self.course}"


class UniversityPriority(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="uni_priorities")
    university = models.CharField(max_length=200)
    city = models.CharField("Город", max_length=120, blank=True)
    specialty = models.CharField("Специальность/направление", max_length=200, blank=True)
    is_targeted = models.BooleanField("Целевое обучение", default=False)
    subjects = models.ManyToManyField(Subject, verbose_name="Предметы для специальности", blank=True)

    priority = models.PositiveIntegerField(help_text="1 — самый высокий приоритет")
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["priority"]
        constraints = [
            models.UniqueConstraint(fields=["user", "priority"], name="unique_priority_per_user"),
            models.UniqueConstraint(
                fields=["user", "university", "specialty"],
                name="unique_uni_specialty_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user} → {self.university} / {self.specialty or 'без направления'} (#{self.priority})"



class AssessmentResult(models.Model):
    class Kind(models.TextChoices):
        PROBNIK = "probnik", _("Пробник")
        TEST = "test", _("Тестирование")
        OLYMPIAD = "olymp", _("Олимпиада")
        FINAL_ESSAY = "essay", _("Итоговое сочинение")
        OTHER = "other", _("Другое")

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assessments")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="assessments")
    title = models.CharField(max_length=200, help_text="Например: Пробник ЕГЭ от … / Тур олимпиады …")
    date = models.DateField()
    score = models.FloatField(null=True, blank=True)
    max_score = models.FloatField(null=True, blank=True)
    place = models.CharField(max_length=200, blank=True, help_text="Место/уровень/организатор")
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="assessments/%Y/%m/", blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    @property
    def percent(self):
        if self.score is not None and self.max_score:
            try:
                return round((self.score / self.max_score) * 100, 1)
            except ZeroDivisionError:
                return None
        return None

    def __str__(self):
        return f"{self.get_kind_display()} {self.subject} — {self.title}"


class ProgressTrackerFile(models.Model):
    file = models.FileField(upload_to="progress_trackers/")
    title = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Файл трекера прогресса"
        verbose_name_plural = "Файл трекера прогресса"

    def __str__(self):
        return self.title or f"Трекер (обновлён: {self.updated_at:%d.%m.%Y})"
