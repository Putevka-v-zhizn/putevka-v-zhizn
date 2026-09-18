import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import ensure_registration_gate
from .access import available_courses_for, study_access_required
from .forms import CourseFilterForm, CourseSelectionForm, UniversityPriorityForm, AssessmentResultForm
from .models import School, Course, CourseSelection, UniversityPriority, AssessmentResult, Subject, ProgressTrackerFile

logger = logging.getLogger(__name__)


@login_required
@study_access_required
def schools_and_courses(request):
    subjects = Subject.objects.all()
    schools = School.objects.all()

    form = CourseFilterForm(request.GET or None)
    qs = available_courses_for(
        request.user,
        Course.objects.select_related("school", "subject"),
    )

    if form.is_valid():
        subject = form.cleaned_data.get("subject")
        q = form.cleaned_data.get("q")
        school_id = request.GET.get("school")
        if subject:
            qs = qs.filter(subject=subject)
        if school_id:
            qs = qs.filter(school_id=school_id)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    paginator = Paginator(qs, 12)
    page = request.GET.get("page")
    courses = paginator.get_page(page)
    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)

    selections = (
        CourseSelection.objects
        .filter(user=request.user)
        .select_related("course__school", "course__subject")
        .order_by("-created_at")
    )
    if request.user.user_info.status == "ALTERNATIVE":
        selections = selections.filter(course__available_to_alternative=True)

    return render(request, "study/schools.html", {
        "subjects": subjects,
        "schools": schools,
        "courses": courses,
        "pagination_query": pagination_params.urlencode(),
        "filter_form": form,
        "selected_school": request.GET.get("school"),
        "selections": selections,
        "active": "study"
    })


@login_required
@study_access_required
@ensure_registration_gate('protected')
def select_course(request, course_id):
    course = get_object_or_404(Course.objects.select_related("school", "subject"), id=course_id)
    if request.user.user_info.status == "ALTERNATIVE" and not course.available_to_alternative:
        raise PermissionDenied
    if request.method == "POST":
        form = CourseSelectionForm(request.POST)
        if form.is_valid():
            selection, created = CourseSelection.objects.get_or_create(
                user=request.user, course=course,
                defaults={"motivation": form.cleaned_data["motivation"],
                          "need_tutor": form.cleaned_data["need_tutor"], }
            )
            if not created:
                selection.motivation = form.cleaned_data["motivation"]
                selection.need_tutor = form.cleaned_data["need_tutor"]
                selection.save()
            messages.success(request, "Ваш выбор сохранён.")
            return redirect("study:schools")
    else:
        initial = {}
        existing = CourseSelection.objects.filter(user=request.user, course=course).first()
        if existing:
            initial["motivation"] = existing.motivation
            initial["need_tutor"] = existing.need_tutor
        form = CourseSelectionForm(initial=initial)

    return render(request, "study/select_course.html", {"course": course, "form": form})


@login_required
@study_access_required
@ensure_registration_gate('protected')
def unselect_course(request, course_id: int):
    if request.method != "POST":
        return redirect("study:schools")
    course = get_object_or_404(Course, id=course_id)
    if request.user.user_info.status == "ALTERNATIVE" and not course.available_to_alternative:
        raise PermissionDenied
    sel = CourseSelection.objects.filter(user=request.user, course=course).first()
    if not sel:
        messages.info(request, "Этот курс не был выбран.")
        return redirect("study:schools")
    sel.delete()
    messages.success(request, "Курс удалён из выбранных.")
    return redirect("study:schools")


@login_required
@study_access_required
@ensure_registration_gate('protected')
def universities(request):
    priorities = (UniversityPriority.objects
                  .filter(user=request.user)
                  .prefetch_related("subjects")
                  .order_by("priority"))

    if request.method == "POST":
        form = UniversityPriorityForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    spec = form.cleaned_data.get("specialty", "")

                    obj, created = UniversityPriority.objects.update_or_create(
                        user=request.user,
                        university=form.cleaned_data["university"],
                        specialty=spec,  # 🔽 добавили в ключ
                        defaults={
                            "priority": form.cleaned_data["priority"],
                            "notes": form.cleaned_data.get("notes", ""),
                            "city": form.cleaned_data.get("city", ""),
                            "is_targeted": form.cleaned_data.get("is_targeted", False),
                        },
                    )
                    obj.subjects.set(form.cleaned_data.get("subjects") or [])
                messages.success(request, "Запись сохранена.")
                return redirect("study:universities")
            except IntegrityError:
                messages.warning(
                    request,
                    "Такой приоритет или направление уже заняты. Выберите другие значения."
                )
        else:
            messages.warning(request, "Исправьте ошибки в форме.")
    else:
        form = UniversityPriorityForm(user=request.user)

    return render(
        request,
        "study/universities.html",
        {"form": form, "priorities": priorities, "active": "study"}
    )


@login_required
@study_access_required
@ensure_registration_gate('protected')
def delete_university_priority(request, pk):
    obj = get_object_or_404(UniversityPriority, pk=pk, user=request.user)
    obj.delete()
    messages.info(request, "Запись удалена.")
    return redirect("study:universities")


@login_required
@study_access_required
@ensure_registration_gate('protected')
def assessments(request):
    results = AssessmentResult.objects.filter(user=request.user).select_related("subject").order_by("-date", "-id")
    tracker = ProgressTrackerFile.objects.order_by("-updated_at").first()

    if request.method == "POST":
        form = AssessmentResultForm(request.POST, request.FILES)
        if form.is_valid():
            inst = form.save(commit=False)
            inst.user = request.user
            inst.save()
            messages.success(request, "Результат добавлен.")
            return redirect("study:assessments")
    else:
        form = AssessmentResultForm()

    return render(request, "study/assessments.html",
                  {"form": form, "results": results, "active": "study", "tracker": tracker})
