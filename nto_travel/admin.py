from django.contrib import admin

from .models import NtoCampaign, NtoConsentRevision, NtoProfile


class NtoManageAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.has_perm("nto_travel.manage_nto_campaign")

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NtoCampaign)
class NtoCampaignAdmin(NtoManageAdmin):
    list_display = ("name", "academic_year", "state", "opens_at", "closes_at")
    list_filter = ("state",)


@admin.register(NtoProfile)
class NtoProfileAdmin(NtoManageAdmin):
    list_display = ("name", "campaign", "final_city", "external_code", "is_active")
    list_filter = ("campaign", "is_active")
    search_fields = ("name", "external_code", "final_city")


@admin.register(NtoConsentRevision)
class NtoConsentRevisionAdmin(NtoManageAdmin):
    list_display = ("version", "published_at")
    def has_change_permission(self, request, obj=None):
        return False if obj else super().has_change_permission(request, obj)

