from django.contrib import admin

from scholar_form.models import ScholarVideo
from .models import Subject, School, Course, CourseSelection, UniversityPriority, AssessmentResult, ProgressTrackerFile


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
    list_display = ("title", "school", "subject", "available_to_alternative")
    list_filter = ("available_to_alternative", "school", "subject")
    search_fields = ("title", "description")


@admin.register(CourseSelection)
class CourseSelectionAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "created_at")
    list_filter = ("course__school", "course__subject")
    search_fields = ("motivation",)

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
