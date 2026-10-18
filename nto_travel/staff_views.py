import json
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook

from .forms import ClarificationForm, DecisionForm, ProfileImportForm
from .models import NtoApplication, NtoApplicationEvent, NtoCampaign, NtoProfile, NtoProfileImport
from .presentation import LABELS, answer_rows
from .services import apply_profile_import, parse_profile_workbook, review_application


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
def detail(request, slug, application_id):
    _require(request, "view_nto_application")
    app = get_object_or_404(NtoApplication.objects.select_related("campaign", "user"), pk=application_id, campaign__slug=slug)
    NtoApplicationEvent.objects.create(application=app, actor=request.user, action="staff_view", old_status=app.status, new_status=app.status)
    return render(request, "nto_travel/staff_detail.html", {
        "application": app, "ranked_profiles": app.ranked_profiles.all(),
        "events": app.events.all()[:50], "clarification_form": ClarificationForm(auto_id="clarification_%s"),
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


def _excel_safe(value):
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        return timezone.localtime(value).strftime("%d.%m.%Y %H:%M:%S %Z")
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@login_required
def export(request, slug):
    _require(request, "export_nto_application")
    campaign = get_object_or_404(NtoCampaign, slug=slug)
    fields = [field for field in NtoApplication._meta.fields if field.name not in {"id", "user", "campaign", "consent_revision", "decided_by", "internal_note"}]
    wb = Workbook()
    ws = wb.active
    ws.title = "Заявки НТО"
    labels = dict(LABELS)
    ws.append(["ID", "ID пользователя", "Сезон", "Профили по приоритету", "Редакция согласия"] + [labels.get(field.name, field.verbose_name) for field in fields])
    for app in _filtered(campaign, request.GET).iterator(chunk_size=200):
        profiles = "; ".join(f"{row.rank}. {row.name_snapshot or row.profile.name} ({row.city_snapshot or row.profile.final_city})" for row in app.ranked_profiles.all())
        ws.append([
            app.pk, app.user_id, _excel_safe(campaign.academic_year), _excel_safe(profiles),
            _excel_safe(app.consent_revision.version if app.consent_revision else ""),
        ] + [_excel_safe(getattr(app, field.name)) for field in fields])
        NtoApplicationEvent.objects.create(application=app, actor=request.user, action="export", old_status=app.status, new_status=app.status)
    out = BytesIO()
    wb.save(out)
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
    book = Workbook()
    sheet = book.active
    sheet.title = "Профили НТО"
    sheet.append(["external_code", "name", "final_city"])
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 50
    sheet.column_dimensions["C"].width = 28
    output = BytesIO()
    book.save(output)
    response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="nto-profiles-template.xlsx"'
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
