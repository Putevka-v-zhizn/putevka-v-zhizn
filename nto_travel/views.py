from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.decorators import ensure_registration_gate
from .forms import FinanceForm, MotivationForm, PersonalForm, ProfileRankingForm
from .models import NtoApplication, NtoCampaign
from .presentation import LABELS, answer_rows
from .services import create_application, save_ranked_profiles, submit_application


def landing(request):
    campaigns = NtoCampaign.objects.filter(state=NtoCampaign.State.PUBLISHED).order_by("-opens_at")
    applications = NtoApplication.objects.filter(user=request.user).select_related("campaign") if request.user.is_authenticated else []
    return render(request, "nto_travel/landing.html", {"campaigns": campaigns, "applications": applications, "suppress_analytics": bool(request.user.is_authenticated)})


def _editable(app):
    if app.status == NtoApplication.Status.DRAFT:
        return app.campaign.accepting
    if app.status == NtoApplication.Status.CLARIFICATION:
        return bool(app.clarification_due_at and timezone.now() < app.clarification_due_at)
    return False


@login_required
@ensure_registration_gate("protected")
def apply_step(request, slug, step):
    campaign = get_object_or_404(NtoCampaign, slug=slug)
    if not NtoApplication.objects.filter(campaign=campaign, user=request.user).exists() and not campaign.accepting:
        raise Http404
    if step not in {"personal", "finance", "motivation"}:
        raise Http404
    app = create_application(request.user, campaign)
    form_class = {"personal": PersonalForm, "finance": FinanceForm, "motivation": MotivationForm}[step]
    if request.method == "POST":
        with transaction.atomic():
            app = NtoApplication.objects.select_for_update().select_related("campaign").get(pk=app.pk)
            if not _editable(app):
                messages.error(request, "Сейчас нельзя изменить эту заявку.")
                return redirect("nto_travel:application", slug=slug)
            form = form_class(request.POST, instance=app)
            ranking = ProfileRankingForm(request.POST, campaign=campaign, application=app) if step == "personal" else None
            form_valid = form.is_valid()
            ranking_valid = ranking.is_valid() if ranking is not None else True
            if form_valid and ranking_valid:
                obj = form.save(commit=False)
                if step == "personal":
                    obj.email = request.user.email
                if step == "motivation":
                    for key in ("universities", "specializations", "achievements"):
                        setattr(obj, key, form.cleaned_data[key])
                obj.save()
                if ranking is not None:
                    save_ranked_profiles(obj, ranking.selected_profiles)
                messages.success(request, "Черновик сохранён.")
                next_step = {"personal": "finance", "finance": "motivation", "motivation": None}[step]
                return redirect("nto_travel:apply_step", slug=slug, step=next_step) if next_step else redirect("nto_travel:review", slug=slug)
    else:
        form = form_class(instance=app)
        ranking = ProfileRankingForm(campaign=campaign, application=app) if step == "personal" else None
    editable = _editable(app)
    if not editable:
        for field in form.fields.values():
            field.disabled = True
        if ranking is not None:
            for field in ranking.fields.values():
                field.disabled = True
    return render(request, "nto_travel/step.html", {
        "campaign": campaign, "application": app, "step": step, "form": form,
        "ranking": ranking, "editable": editable, "suppress_analytics": True,
    })


@login_required
@ensure_registration_gate("protected")
def review(request, slug):
    app = get_object_or_404(NtoApplication.objects.select_related("campaign"), campaign__slug=slug, user=request.user)
    return render(request, "nto_travel/review.html", {
        "application": app, "ranked_profiles": app.ranked_profiles.select_related("profile"),
        "editable": _editable(app), "answer_rows": answer_rows(app), "suppress_analytics": True,
    })


@login_required
@ensure_registration_gate("protected")
@require_POST
def submit(request, slug):
    app = get_object_or_404(NtoApplication, campaign__slug=slug, user=request.user)
    try:
        submit_application(app.pk, request.user, consent_confirmed=request.POST.get("accept_consent") == "on")
    except ValidationError as exc:
        if hasattr(exc, "message_dict"):
            for key, errors in exc.message_dict.items():
                label = dict(LABELS).get(key, "Профили НТО" if key == "profiles" else "Заявка")
                messages.error(request, f"{label}: {'; '.join(errors)}")
        else:
            messages.error(request, "; ".join(exc.messages))
        return redirect("nto_travel:review", slug=slug)
    messages.success(request, "Заявка отправлена.")
    return redirect("nto_travel:application", slug=slug)


@login_required
@ensure_registration_gate("protected")
def application(request, slug):
    app = get_object_or_404(NtoApplication.objects.select_related("campaign"), campaign__slug=slug, user=request.user)
    return render(request, "nto_travel/application.html", {
        "application": app, "ranked_profiles": app.ranked_profiles.all(),
        "editable": _editable(app), "answer_rows": answer_rows(app), "suppress_analytics": True,
    })
