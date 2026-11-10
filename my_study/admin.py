from django import forms
from django.contrib import admin

from scholar_form.models import ScholarVideo
from .models import Subject, School, Course, CourseSelection, UniversityPriority, AssessmentResult, ProgressTrackerFile, PreparationDirection


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "is_top")
    list_filter = ("is_top",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "website")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "school", "subject", "available_to_alternative", "is_olympiad")
    list_editable = ("available_to_alternative", "is_olympiad")
    list_filter = ("available_to_alternative", "is_olympiad", "school", "subject")
    search_fields = ("title", "description")


@admin.register(CourseSelection)
class CourseSelectionAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "created_at")
    list_filter = ("course__school", "course__subject")
    search_fields = ("user__username", "user__first_name", "user__last_name", "course__title", "motivation")
    raw_id_fields = ("user",)
    list_select_related = ("user", "course")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        PreparationDirection.objects.get_or_create(
            user=obj.user, is_olympiad=obj.course.is_olympiad,
            subject_id=None if obj.course.is_olympiad else obj.course.subject_id,
        )

@admin.register(UniversityPriority)
class UniversityPriorityAdmin(admin.ModelAdmin):
    list_display = ("user", "university", "priority")
    list_filter = ("university",)
    ordering = ("user", "priority")


@admin.register(AssessmentResult)
class AssessmentResultAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "subject", "title", "date", "score", "max_score")
    list_filter = ("kind", "subject", "date")
    search_fields = ("title", "notes", "place")


@admin.register(ProgressTrackerFile)
class ProgressTrackerFileAdmin(admin.ModelAdmin):
    list_display = ("title", "updated_at")


class PreparationDirectionAdminForm(forms.ModelForm):
    class Meta:
        model = PreparationDirection
        fields = "__all__"
        labels = {
            "user": "Ребёнок",
            "subject": "Предмет ЕГЭ",
            "is_olympiad": "Олимпиады",
            "not_started": "Не начал готовиться",
            "independently": "Готовится самостоятельно",
            "with_tutor_or_school": "Готовится с репетитором / в школе",
        }
        help_texts = {
            "subject": "Для олимпиад оставьте предмет пустым.",
            "not_started": "Нельзя сочетать с другими способами. Все пустые отметки означают, что способ не указан.",
        }

    def clean(self):
        data = super().clean()
        if data.get("is_olympiad") and data.get("subject"):
            self.add_error("subject", "Для направления «Олимпиады» предмет не указывается.")
        elif not data.get("is_olympiad") and not data.get("subject"):
            self.add_error("subject", "Выберите предмет ЕГЭ или отметьте «Олимпиады».")
        if data.get("not_started") and (data.get("independently") or data.get("with_tutor_or_school")):
            self.add_error("not_started", "«Не начал» нельзя сочетать с другими способами подготовки.")
        return data


@admin.register(PreparationDirection)
class PreparationDirectionAdmin(admin.ModelAdmin):
    form = PreparationDirectionAdminForm
    list_display = ("user", "direction_name", "not_started", "independently", "with_tutor_or_school", "updated_at")
    list_filter = ("is_olympiad", "subject", "not_started", "independently", "with_tutor_or_school")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("updated_at",)
    list_select_related = ("user", "subject")
    actions = None

    @admin.display(description="Направление")
    def direction_name(self, obj):
        return obj.title

    def has_delete_permission(self, request, obj=None):
        if not super().has_delete_permission(request, obj):
            return False
        if obj is None:
            return True
        selections = CourseSelection.objects.filter(user_id=obj.user_id, course__is_olympiad=obj.is_olympiad)
        if not obj.is_olympiad:
            selections = selections.filter(course__subject_id=obj.subject_id)
        return not selections.exists()
