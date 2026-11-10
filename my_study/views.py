import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.views.decorators.http import require_POST
from .forms import PreparationAddForm, PreparationMethodsForm
from .models import PreparationDirection
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
    qs = available_courses_for(
        request.user,
        Course.objects.filter(is_olympiad=False).select_related("school", "subject"),
    )
    schools = School.objects.filter(courses__in=qs).distinct()

    form = CourseFilterForm(request.GET or None)

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
        .filter(user=request.user, course__is_olympiad=False)
        .select_related("course__school", "course__subject")
        .order_by("-created_at")
    )
    if request.user.user_info.status == "ALTERNATIVE":
        selections = selections.filter(course__available_to_alternative=True)

    # Synchronize legacy selections and changes to course classification.
    all_selections = list(CourseSelection.objects.filter(user=request.user).select_related("course"))
    for selection in all_selections:
        ensure_course_direction(request.user, selection.course)
    grouped = {}
    for selection in selections:
        key = None if selection.course.is_olympiad else selection.course.subject_id
        grouped.setdefault(key, []).append(selection)
    directions = list(PreparationDirection.objects.filter(user=request.user, is_olympiad=False).select_related("subject"))
    for direction in directions:
        key = None if direction.is_olympiad else direction.subject_id
        direction.selections = grouped.get(key, [])
        direction.has_courses = any(
            sel.course.is_olympiad if direction.is_olympiad
            else not sel.course.is_olympiad and sel.course.subject_id == direction.subject_id
            for sel in all_selections
        )
        direction.methods_form = PreparationMethodsForm(initial={
            field: getattr(direction, field) for field in PreparationMethodsForm.base_fields
        }, prefix=f"preparation-{direction.pk}")

    return render(request, "study/schools.html", {
        "directions": directions,
        "preparation_add_form": PreparationAddForm(),
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
    course = get_object_or_404(Course.objects.select_related("school", "subject"), id=course_id, is_olympiad=False)
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
            ensure_course_direction(request.user, course)
            messages.success(request, "Твой выбор сохранён.")
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
                    "Такой приоритет или направление уже заняты. Выбери другие значения."
                )
        else:
            messages.warning(request, "Исправь ошибки в форме.")
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


def ensure_course_direction(user, course):
    if course.is_olympiad:
        return None
    return PreparationDirection.objects.get_or_create(
        user=user, is_olympiad=course.is_olympiad,
        subject_id=None if course.is_olympiad else course.subject_id,
    )[0]


@login_required
@study_access_required
@ensure_registration_gate('protected')
@require_POST
def add_preparation(request):
    form = PreparationAddForm(request.POST)
    if form.is_valid():
        value = form.cleaned_data["direction"]
        PreparationDirection.objects.get_or_create(
            user=request.user, is_olympiad=False, subject_id=int(value),
        )
        messages.success(request, "Направление подготовки добавлено.")
    else:
        messages.error(request, "Выбери предмет ЕГЭ из списка.")
    return redirect("study:schools")


@login_required
@study_access_required
@ensure_registration_gate('protected')
@require_POST
def update_preparation(request, pk):
    direction = get_object_or_404(PreparationDirection, pk=pk, user=request.user, is_olympiad=False)
    form = PreparationMethodsForm(request.POST, prefix=f"preparation-{pk}")
    if form.is_valid():
        for field, value in form.cleaned_data.items():
            setattr(direction, field, value)
        direction.save()
        messages.success(request, "Способы подготовки сохранены.")
    else:
        messages.error(request, "«Не начал» нельзя сочетать с другими способами подготовки. Изменения не сохранены.")
    return redirect("study:schools")


@login_required
@study_access_required
@ensure_registration_gate('protected')
@require_POST
def delete_preparation(request, pk):
    direction = get_object_or_404(PreparationDirection, pk=pk, user=request.user, is_olympiad=False)
    selections = CourseSelection.objects.filter(user=request.user, course__is_olympiad=direction.is_olympiad)
    if not direction.is_olympiad:
        selections = selections.filter(course__subject_id=direction.subject_id)
    if selections.exists():
        messages.error(request, "Сначала удали выбранные курсы этого направления. Если курс недоступен, обратись к администратору.")
    else:
        direction.delete()
        messages.success(request, "Направление подготовки удалено.")
    return redirect("study:schools")
