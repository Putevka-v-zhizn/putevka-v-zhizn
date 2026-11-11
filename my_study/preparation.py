"""Shared preparation presentation for children and staff."""
from .models import CourseSelection, PreparationDirection


def ensure_course_direction(user, course, *, clear_not_started=True):
    if course.subject.is_olympiad:
        return None
    direction, _ = PreparationDirection.objects.get_or_create(user=user, subject_id=course.subject_id)
    if clear_not_started and direction.not_started:
        direction.not_started = False
        direction.save(update_fields=["not_started", "updated_at"])
    return direction


def preparation_rows(user, *, visible_selections=None):
    selections = list(CourseSelection.objects.filter(user=user, course__subject__is_olympiad=False)
                      .select_related("course__school", "course__subject", "course__duration")
                      .order_by("-created_at", "-id"))
    by_subject = {
        direction.subject_id: {"subject": direction.subject, "direction": direction, "selections": [], "has_courses": False}
        for direction in PreparationDirection.objects.filter(user=user, subject__is_olympiad=False).select_related("subject")
    }
    for selection in selections:
        row = by_subject.setdefault(selection.course.subject_id, {
            "subject": selection.course.subject, "direction": None, "selections": [], "has_courses": False,
        })
        row["has_courses"] = True
    for selection in selections if visible_selections is None else visible_selections:
        if not selection.course.subject.is_olympiad:
            by_subject[selection.course.subject_id]["selections"].append(selection)
    for row in by_subject.values():
        direction = row["direction"]
        child_methods, staff_methods = [], []
        if row["has_courses"]:
            child_methods.append("Готовлюсь на курсах")
            staff_methods.append("Готовится на курсах")
        if direction:
            if direction.not_started and not row["has_courses"]:
                child_methods.append("Не начал готовиться к этому предмету")
                staff_methods.append("Не начал готовиться к этому предмету")
            if direction.independently:
                child_methods.append("Готовлюсь самостоятельно")
                staff_methods.append("Готовится самостоятельно")
            if direction.with_tutor_or_school:
                child_methods.append("Готовлюсь с репетитором / в школе")
                staff_methods.append("Готовится с репетитором / в школе")
        row.update(child_methods=child_methods, staff_methods=staff_methods, has_answer=bool(child_methods))
    return sorted(by_subject.values(), key=lambda row: row["subject"].name)
