from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class NtoConsentRevision(models.Model):
    version = models.CharField(max_length=40, unique=True)
    text = models.TextField()
    published_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.version

    def save(self, *args, **kwargs):
        if self.pk and NtoConsentRevision.objects.filter(pk=self.pk).exists():
            old = NtoConsentRevision.objects.get(pk=self.pk)
            if old.text != self.text or old.version != self.version or old.published_at != self.published_at:
                raise ValidationError("Опубликованную редакцию согласия нельзя изменить.")
        super().save(*args, **kwargs)


class NtoCampaign(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликован"
        ARCHIVED = "archived", "Архив"

    slug = models.SlugField(unique=True)
    academic_year = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    state = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)
    consent_revision = models.ForeignKey(NtoConsentRevision, on_delete=models.PROTECT, null=True, blank=True)

    def clean(self):
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise ValidationError({"closes_at": "Закрытие должно быть позднее открытия."})
        if self.state == self.State.PUBLISHED:
            if not self.consent_revision_id:
                raise ValidationError({"consent_revision": "Для публикации требуется согласие."})
            if not self.pk or not any(
                (profile.final_city or "").strip()
                for profile in self.profiles.filter(is_active=True).only("final_city")
            ):
                raise ValidationError("Для публикации нужен хотя бы один активный профиль с городом.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def accepting(self):
        now = timezone.now()
        return self.state == self.State.PUBLISHED and self.opens_at <= now < self.closes_at

    def __str__(self):
        return self.name

    class Meta:
        permissions = [("manage_nto_campaign", "Управлять сезонами НТО")]


class NtoProfile(models.Model):
    campaign = models.ForeignKey(NtoCampaign, on_delete=models.PROTECT, related_name="profiles")
    external_code = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    final_city = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "external_code"], name="nto_profile_code_unique")]
        ordering = ["name"]

    def clean(self):
        for field in ("external_code", "name", "final_city"):
            if not (getattr(self, field) or "").strip():
                raise ValidationError({field: "Поле обязательно."})

    def save(self, *args, **kwargs):
        for field in ("external_code", "name", "final_city"):
            setattr(self, field, (getattr(self, field) or "").strip())
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class NtoApplication(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SUBMITTED = "submitted", "Подана"
        CLARIFICATION = "clarification", "На уточнении"
        APPROVED = "approved", "Одобрена"
        REJECTED = "rejected", "Отказано"

    class SupportAnswer(models.TextChoices):
        FULL = "full", "Оплатят полностью"
        PARTIAL = "partial", "Оплатят частично"
        NO = "no", "Не смогут оплатить"
        NOT_DISCUSSED = "not_discussed", "Ещё не обсуждали"

    class IncomeDisclosure(models.TextChoices):
        AMOUNT = "amount", "Укажу сумму"
        UNKNOWN = "unknown", "Затрудняюсь ответить"
        DECLINED = "declined", "Не хочу указывать"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="nto_applications")
    campaign = models.ForeignKey(NtoCampaign, on_delete=models.PROTECT, related_name="applications")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    last_name = models.CharField(max_length=255, blank=True)
    first_name = models.CharField(max_length=255, blank=True)
    middle_name = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=255, blank=True, db_index=True)
    city = models.CharField(max_length=255, blank=True)
    school_class = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(11)])
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    telegram = models.CharField(max_length=100, blank=True)
    is_adult = models.BooleanField(null=True, blank=True)
    parent_name = models.CharField(max_length=255, blank=True)
    parent_role = models.CharField(max_length=100, blank=True)
    parent_phone = models.CharField(max_length=20, blank=True)
    finalist_declared = models.BooleanField(default=False)
    parent_contact_declared = models.BooleanField(default=False)
    final_city = models.CharField(max_length=255, blank=True, db_index=True)
    previous_final = models.BooleanField(null=True, blank=True)
    previous_payers = models.JSONField(default=list, blank=True)
    possible_payers = models.JSONField(default=list, blank=True)
    school_support = models.CharField(max_length=20, choices=SupportAnswer.choices, blank=True)
    parent_support = models.CharField(max_length=20, choices=SupportAnswer.choices, blank=True)
    ticket_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(10000000)])
    income_disclosure = models.CharField(max_length=20, choices=IncomeDisclosure.choices, blank=True)
    income_per_member = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    income_proof = models.BooleanField(null=True, blank=True)
    family_material_status = models.CharField(max_length=2, blank=True)
    circumstances = models.JSONField(default=list, blank=True)
    circumstance_proof = models.BooleanField(null=True, blank=True)
    situation_details = models.TextField(blank=True)
    universities = models.JSONField(default=list, blank=True)
    specializations = models.JSONField(default=list, blank=True)
    achievements = models.JSONField(default=list, blank=True)
    no_achievements = models.BooleanField(default=False)
    olympiad_plans = models.TextField(blank=True)
    preparation_methods = models.JSONField(default=list, blank=True)
    preparation_details = models.TextField(blank=True)
    nto_goal = models.TextField(blank=True)
    refused_olympiads = models.BooleanField(null=True, blank=True)
    refusal_reason = models.TextField(blank=True)
    admission_without_trip = models.TextField(blank=True)
    has_admission_advantages = models.BooleanField(null=True, blank=True)
    advantage_details = models.TextField(blank=True)
    free_thoughts = models.TextField(blank=True)
    consent_revision = models.ForeignKey(NtoConsentRevision, on_delete=models.PROTECT, null=True, blank=True)
    consent_accepted_at = models.DateTimeField(null=True, blank=True)
    public_comment = models.TextField(blank=True)
    internal_note = models.TextField(blank=True)
    clarification_due_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="nto_decisions")
    decided_at = models.DateTimeField(null=True, blank=True)
    last_submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "user"], name="nto_one_application_per_campaign")]
        indexes = [models.Index(fields=["campaign", "status"], name="nto_campaign_status_idx")]
        permissions = [
            ("view_nto_application", "Просматривать заявки НТО"),
            ("review_nto_application", "Рассматривать заявки НТО"),
            ("export_nto_application", "Выгружать заявки НТО"),
        ]

    def __str__(self):
        return f"{self.campaign}: {self.user}"


class NtoApplicationProfile(models.Model):
    application = models.ForeignKey(NtoApplication, on_delete=models.CASCADE, related_name="ranked_profiles")
    profile = models.ForeignKey(NtoProfile, on_delete=models.PROTECT)
    rank = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    name_snapshot = models.CharField(max_length=255, blank=True)
    city_snapshot = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(fields=["application", "profile"], name="nto_application_profile_unique"),
            models.UniqueConstraint(fields=["application", "rank"], name="nto_application_rank_unique"),
            models.CheckConstraint(check=Q(rank__gte=1), name="nto_rank_positive"),
        ]

    def clean(self):
        if self.application_id and self.profile_id and self.application.campaign_id != self.profile.campaign_id:
            raise ValidationError("Профиль относится к другому сезону.")


class NtoApplicationEvent(models.Model):
    application = models.ForeignKey(NtoApplication, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=40)
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class NtoProfileImport(models.Model):
    campaign = models.ForeignKey(NtoCampaign, on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    file_sha256 = models.CharField(max_length=64)
    row_count = models.PositiveIntegerField()
    rows = models.JSONField(default=list)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
