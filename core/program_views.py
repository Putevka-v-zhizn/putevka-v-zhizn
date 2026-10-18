from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.decorators import ensure_registration_gate
from core.models import RegistrationPersonalData
from core.services.programs import get_program_preferences, select_program


@login_required
@ensure_registration_gate('protected')
@require_GET
def programs(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect('index')
    return render(request, 'core/programs.html', {
        'preferences': get_program_preferences(request.user),
        'suppress_analytics': True,
    })


@login_required
@ensure_registration_gate('protected')
@require_POST
def program_select(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect('index')
    program = request.POST.get('program', '')
    try:
        select_program(request.user, program)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        return redirect('programs')
    if program == 'nto':
        from nto_travel.models import NtoCampaign
        attempt = RegistrationPersonalData.objects.filter(user=request.user).first()
        if attempt and attempt.nto_campaign_slug:
            campaign = NtoCampaign.objects.filter(slug=attempt.nto_campaign_slug).first()
            attempt.nto_campaign_slug = ''
            attempt.save(update_fields=['nto_campaign_slug'])
            if campaign and campaign.accepting:
                return redirect('nto_travel:apply_step', slug=campaign.slug, step='personal')
        return redirect('nto_travel:landing')
    from scholar_form.models import UserInfo
    info, _ = UserInfo.objects.get_or_create(user=request.user)
    if info.status == 'CANDIDATE' and info.form_status == 'draft':
        return redirect('apply')
    return redirect('index')
