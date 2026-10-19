from io import BytesIO
from copy import deepcopy

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F, Q
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook

from .forms import ClarificationForm, DecisionForm, ProfileImportForm, PersonalForm, FinanceForm, MotivationForm, ProfileRankingForm
from .exporting import application_workbook
from .models import NtoApplication, NtoApplicationEvent, NtoCampaign, NtoProfile, NtoProfileImport
from .presentation import LABELS, answer_rows, event_rows
from .services import apply_profile_import, parse_profile_workbook, review_application, save_ranked_profiles


def _require(request, permission):
    if not request.user.is_staff or not request.user.has_perm(f"nto_travel.{permission}"):
        raise PermissionDenied


def _filtered(campaign, params):
    qs = NtoApplication.objects.filter(campaign=campaign).select_related("user", "campaign").prefetch_related("ranked_profiles__profile")
    if params.get("status") in dict(NtoApplication.Status.choices):
        qs = qs.filter(status=params["status"])
    if params.get("region"):
        qs = qs.filter(region__icontains=params["region"].strip()[:100])
    if params.get("city"):
        qs = qs.filter(final_city__icontains=params["city"].strip()[:100])
    if params.get("profile"):
        qs = qs.filter(ranked_profiles__rank=1, ranked_profiles__profile__external_code=params["profile"][:100])
    if params.get("q"):
        for term in params["q"].strip()[:100].split():
            qs = qs.filter(
                Q(last_name__icontains=term) | Q(first_name__icontains=term)
                | Q(middle_name__icontains=term) | Q(email__icontains=term)
            )
    return qs.distinct().order_by("-last_submitted_at", "-created_at")


@login_required
def queue(request):
    _require(request, "view_nto_application")
    campaigns = NtoCampaign.objects.order_by("-opens_at")
    slug = request.GET.get("campaign")
    campaign = get_object_or_404(NtoCampaign, slug=slug) if slug else campaigns.first()
    applications = _filtered(campaign, request.GET) if campaign else []
    return render(request, "nto_travel/staff_queue.html", {
        "campaigns": campaigns, "campaign": campaign, "applications": applications,
        "profiles": NtoProfile.objects.filter(campaign=campaign).order_by("name") if campaign else [],
        "suppress_analytics": True,
    })


@login_required
def edit(request, slug, application_id):
    _require(request, "view_nto_application")
    _require(request, "manage_nto_campaign")
    with transaction.atomic():
        query = NtoApplication.objects.select_related("campaign", "user")
        if request.method == "POST":
            query = query.select_for_update()
        app = get_object_or_404(query, pk=application_id, campaign__slug=slug)
        if request.method == "GET":
            NtoApplicationEvent.objects.create(application=app, actor=request.user, action="staff_view", old_status=app.status, new_status=app.status)
        data = request.POST if request.method == "POST" else None
        before = {key: deepcopy(getattr(app, key)) for key, _ in LABELS}
        forms = [cls(data, instance=app, prefix=prefix) for cls, prefix in (
            (PersonalForm, "personal"), (FinanceForm, "finance"), (MotivationForm, "motivation"),
        )]
        for key in ("finalist_declared", "parent_contact_declared"):
            forms[0].fields.pop(key, None)
        ranking = ProfileRankingForm(data, campaign=app.campaign, application=app)
        previous = {row.profile_id: (row.name_snapshot, row.city_snapshot) for row in app.ranked_profiles.all()}
        old_order = list(app.ranked_profiles.order_by("rank").values_list("profile_id", flat=True))
        if request.method == "POST":
            valid = [form.is_valid() for form in forms] + [ranking.is_valid()]
            if all(valid):
                for form in forms:
                    form.save(commit=False)
                for key in ("universities", "specializations", "achievements"):
                    setattr(app, key, forms[2].cleaned_data[key])
                profiles = ranking.selected_profiles
                profiles_changed = old_order != [profile.pk for profile in profiles]
                if profiles_changed:
                    save_ranked_profiles(app, profiles)
                    for row in app.ranked_profiles.select_related("profile"):
                        row.name_snapshot, row.city_snapshot = previous.get(row.profile_id, (row.profile.name, row.profile.final_city))
                        row.save(update_fields=["name_snapshot", "city_snapshot"])
                first = app.ranked_profiles.select_related("profile").order_by("rank").first()
                app.final_city = (first.city_snapshot or first.profile.final_city) if first else ""
                changed = [label for key, label in LABELS if before[key] != getattr(app, key)]
                if profiles_changed:
                    changed.append("Профили по приоритету")
                if changed:
                    app.save()
                    NtoApplicationEvent.objects.create(application=app, actor=request.user, action="staff_edit", old_status=app.status, new_status=app.status, comment="Изменены поля: " + ", ".join(changed))
                messages.success(request, "Изменения анкеты сохранены.")
                return redirect("nto_staff:detail", slug=slug, application_id=app.pk)
    return render(request, "nto_travel/staff_edit.html", {
        "application": app, "forms": forms, "ranking": ranking, "suppress_analytics": True,
    })


@login_required
def detail(request, slug, application_id):
    _require(request, "view_nto_application")
    app = get_object_or_404(NtoApplication.objects.select_related("campaign", "user"), pk=application_id, campaign__slug=slug)
    NtoApplicationEvent.objects.create(application=app, actor=request.user, action="staff_view", old_status=app.status, new_status=app.status)
    events = app.events.select_related("actor").order_by("-created_at", "-pk")
    access_events = events.filter(action__in=["staff_view", "export"])
    history_events = events.exclude(action__in=["staff_view", "export"])
    return render(request, "nto_travel/staff_detail.html", {
        "application": app, "ranked_profiles": app.ranked_profiles.all(),
        "events": event_rows(history_events[:50]), "history_count": history_events.count(),
        "access_events": event_rows(access_events[:50]), "access_count": access_events.count(),
        "clarification_form": ClarificationForm(auto_id="clarification_%s"),
        "decision_form": DecisionForm(auto_id="decision_%s"), "answer_rows": answer_rows(app), "suppress_analytics": True,
    })


@login_required
@require_POST
def action(request, slug, application_id, action_name):
    _require(request, "review_nto_application")
    app = get_object_or_404(NtoApplication, pk=application_id, campaign__slug=slug)
    if action_name not in {"clarify", "approve", "reject"}:
        raise PermissionDenied
    if action_name == "clarify":
        form = ClarificationForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Укажите комментарий и корректный срок уточнения.")
            return redirect("nto_staff:detail", slug=slug, application_id=application_id)
        comment = form.cleaned_data["comment"]
        due_at = form.cleaned_data["due_at"]
    else:
        form = DecisionForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Проверьте комментарий.")
            return redirect("nto_staff:detail", slug=slug, application_id=application_id)
        comment, due_at = form.cleaned_data["comment"], None
    try:
        review_application(app.pk, request.user, action_name, comment=comment, due_at=due_at)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Решение сохранено.")
    return redirect("nto_staff:detail", slug=slug, application_id=application_id)


@login_required
@require_POST
def save_note(request, slug, application_id):
    _require(request, "review_nto_application")
    app = get_object_or_404(NtoApplication, pk=application_id, campaign__slug=slug)
    app.internal_note = (request.POST.get("internal_note") or "").strip()[:5000]
    app.save(update_fields=["internal_note", "updated_at"])
    NtoApplicationEvent.objects.create(application=app, actor=request.user, action="internal_note", old_status=app.status, new_status=app.status)
    return redirect("nto_staff:detail", slug=slug, application_id=application_id)


@login_required
def export(request, slug):
    _require(request, "export_nto_application")
    campaign = get_object_or_404(NtoCampaign, slug=slug)
    applications = list(_filtered(campaign, request.GET).order_by(F("last_submitted_at").desc(nulls_last=True), "-pk"))
    wb = application_workbook(applications)
    out = BytesIO()
    wb.save(out)
    NtoApplicationEvent.objects.bulk_create([
        NtoApplicationEvent(application=app, actor=request.user, action="export", old_status=app.status, new_status=app.status)
        for app in applications
    ])
    response = HttpResponse(out.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="nto-{campaign.slug}.xlsx"'
    return response


@login_required
def profile_import(request, slug):
    _require(request, "manage_nto_campaign")
    campaign = get_object_or_404(NtoCampaign, slug=slug)
    form = ProfileImportForm(request.POST or None, request.FILES or None)
    preview = None
    if request.method == "POST" and form.is_valid():
        rows, errors, digest = parse_profile_workbook(form.cleaned_data["file"])
        if errors:
            for error in errors[:20]:
                messages.error(request, error)
        else:
            preview = NtoProfileImport.objects.create(
                campaign=campaign, actor=request.user, file_sha256=digest,
                row_count=len(rows), rows=rows,
            )
    return render(request, "nto_travel/staff_import.html", {
        "campaign": campaign, "form": form, "preview": preview,
        "suppress_analytics": True,
    })


@login_required
def profile_template(request, slug):
    _require(request, "manage_nto_campaign")
    get_object_or_404(NtoCampaign, slug=slug)
    return _profile_workbook([], "nto-profiles-template.xlsx")


@login_required
def profile_export(request, slug):
    _require(request, "manage_nto_campaign")
    campaign = get_object_or_404(NtoCampaign, slug=slug)
    rows = NtoProfile.objects.filter(campaign=campaign, is_active=True).order_by("external_code").values_list("external_code", "name", "final_city")
    return _profile_workbook(rows, f"nto-profiles-{campaign.slug}.xlsx")


def _profile_workbook(rows, filename):
    book = Workbook()
    sheet = book.active
    sheet.title = "Профили НТО"
    sheet.append(["external_code", "name", "final_city"])
    for row in rows:
        sheet.append(list(row))
        # Explicit text cells preserve codes and prevent spreadsheet formulas.
        for cell in sheet[sheet.max_row]:
            cell.data_type = "s"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 50
    sheet.column_dimensions["C"].width = 28
    output = BytesIO()
    book.save(output)
    response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_POST
def confirm_import(request, slug, batch_id):
    _require(request, "manage_nto_campaign")
    campaign = get_object_or_404(NtoCampaign, slug=slug)
    try:
        apply_profile_import(batch_id, campaign, request.user)
    except (ValidationError, NtoProfileImport.DoesNotExist) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Справочник профилей обновлён.")
    return redirect("nto_staff:queue")
