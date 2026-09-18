import uuid

from django.contrib import admin

from .models import (
    FamilyIncomeAuditEvent, FamilyIncomeCase, FamilyIncomeDecision,
    FamilyIncomeDocument, FamilyIncomeInstruction, IncomeEvidence, IncomeYear,
    SocialBenefitEvidence,
)


class FamilyIncomeDocumentInline(admin.TabularInline):
    model = FamilyIncomeDocument
    extra = 0
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("document", "added_by")


class FamilyIncomeDecisionInline(admin.TabularInline):
    model = FamilyIncomeDecision
    extra = 0
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("created_by", "updated_by")


@admin.register(FamilyIncomeCase)
class FamilyIncomeCaseAdmin(admin.ModelAdmin):
    list_display = ("user_info", "status", "family_members_count", "low_income_recognized", "updated_at")
    list_filter = ("status", "low_income_recognized")
    search_fields = ("user_info__user__username", "user_info__last_name", "user_info__first_name")
    raw_id_fields = ("user_info",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (FamilyIncomeDocumentInline, FamilyIncomeDecisionInline)


@admin.register(FamilyIncomeDocument)
class FamilyIncomeDocumentAdmin(admin.ModelAdmin):
    list_display = ("document", "case", "category", "review_status", "added_by", "updated_at")
    list_filter = ("category", "review_status")
    search_fields = ("candidate_comment", "staff_comment", "document__caption")
    raw_id_fields = ("case", "document", "added_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(IncomeEvidence)
class IncomeEvidenceAdmin(admin.ModelAdmin):
    list_display = ("owner_name", "year", "gross_amount", "net_amount", "average_monthly_amount", "months_received")
    list_filter = ("year",)
    search_fields = ("owner_name", "absence_reason", "staff_decision_comment")
    raw_id_fields = ("family_income_document",)


@admin.register(SocialBenefitEvidence)
class SocialBenefitEvidenceAdmin(admin.ModelAdmin):
    list_display = ("recipient_name", "benefit_description", "family_income_document")
    search_fields = ("recipient_name", "benefit_description")
    raw_id_fields = ("family_income_document",)


@admin.register(FamilyIncomeDecision)
class FamilyIncomeDecisionAdmin(admin.ModelAdmin):
    list_display = ("case", "year", "amount_per_member", "is_low_income_recognized", "updated_by", "updated_at")
    list_filter = ("year", "is_low_income_recognized")
    raw_id_fields = ("case", "created_by", "updated_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(IncomeYear)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = ("__str__", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")



@admin.register(FamilyIncomeInstruction)
class FamilyIncomeInstructionAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "text", "version")
    raw_id_fields = ("updated_by",)
    readonly_fields = ("updated_at",)
    fieldsets = (
        ("Содержание", {"fields": ("title", "text")}),
        ("Материалы", {"fields": ("url", "file")}),
        ("Публикация", {"fields": ("status", "updated_at")}),
    )

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.version:
            obj.version = uuid.uuid4().hex
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(FamilyIncomeAuditEvent)
class FamilyIncomeAuditEventAdmin(admin.ModelAdmin):
    list_display = ("case", "action", "target_model", "target_id", "actor", "created_at")
    list_filter = ("action", "target_model")
    search_fields = ("reason", "target_model")
    raw_id_fields = ("case", "actor")
    readonly_fields = ("case", "actor", "action", "target_model", "target_id", "before", "after", "reason", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
