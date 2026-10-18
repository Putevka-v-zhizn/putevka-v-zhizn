import logging
import random
import uuid

import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password, password_validators_help_text_html
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

import config
from review_by_tutor.utils.selection_stages import require_selection_step
from .decorators import ensure_registration_gate
from .forms import CustomUserCreationForm, RegistrationForm, VerifyEmailForm, PhoneNumberForm, MotivationLetterForm, \
    FeedbackForm
from .models import TelegramAccount, RegistrationPersonalData, MotivationLetterInstruction
from scholar_form.models import UserInfo
from datetime import datetime, timedelta
from .models import MotivationLetter
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.db import transaction

from .forms import SendNotificationForm
from .models import UserNotification, Notification

from .services.email_service import send_email_message, send_email_verification_code
from .services.zvonok_service import initiate_zvonok_verification, poll_zvonok_status
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET", "POST"])
def feedback_view(request):
    feedback_email = settings.CONTACT_EMAIL
    if request.method == "POST":
        form = FeedbackForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = request.user

            user_info = getattr(user, "user_info", None)

            full_name = user.get_full_name() or user.username
            email = user.email or "-"
            phone = getattr(user_info, "phone", "-") if user_info else "-"

            tg = getattr(user, "telegram_account", None)
            tg_user = getattr(tg, "username", None)
            tg_display = f"@{tg_user}" if tg_user else "-"
            subject = f"Обратная связь с сайта от пользователя #{user.id}"

            text = (
                "Обратная связь с сайта\n\n"
                f"Пользователь: {full_name} (id={user.id})\n"
                f"Email: {email}\n"
                f"Телефон: {phone}\n"
                f"Телеграм: {tg_display}\n\n"
                f"Сообщение:\n{cd['message']}"
            )
            html = (
                "<b>Обратная связь с сайта</b><br><br>"
                f"<b>Пользователь:</b> {full_name} (id={user.id})<br>"
                f"<b>Email:</b> {email}<br>"
                f"<b>Телефон:</b> {phone}<br>"
                f"<b>Телеграм:</b> {tg_display}<br><br>"
                f"<b>Сообщение:</b><br>{cd['message'].replace(chr(10), '<br>')}"
            )

            logger.info("Получена обратная связь от user_id=%s", user.id)

            try:
                send_email_message(
                    subject=subject,
                    to=[feedback_email],
                    text=text,
                    html=html,
                )
            except Exception:
                messages.error(request, "Не удалось отправить сообщение. Попробуйте позже.")
                return render(request, "feedback.html", {"form": form, "active": "feedback"})

            messages.success(request, "Спасибо! Сообщение отправлено.")
            return redirect("feedback")
    else:
        form = FeedbackForm()

    return render(request, "feedback.html", {"form": form, "active": "feedback"})

@login_required()
@ensure_registration_gate('protected')
def index(request):
    if request.user.is_staff:
        return redirect('/staff/users')
    return render(request, 'core/index.html')


def _registration_nto_slug(request):
    from nto_travel.models import NtoCampaign

    slug = (request.POST.get('nto') or request.GET.get('nto') or '').strip()
    if slug and NtoCampaign.objects.filter(slug=slug, state=NtoCampaign.State.PUBLISHED).exists():
        return slug
    return ''


@ensure_registration_gate('entry')
def register_initial(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']

            if User.objects.filter(email=email, is_active=True).exists():
                form.add_error('email', 'Пользователь с таким email уже зарегистрирован.')
            else:
                logger.info("Начата регистрация для нового пользователя.")
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    is_active=True,
                )
                telegram_account = TelegramAccount.objects.create(
                    user=user,
                    activation_token=uuid.uuid4()
                )
                user_info = UserInfo.objects.create(user=user)

                new_attempt = RegistrationPersonalData.objects.create(
                    user=user,
                    telegram_account=telegram_account,
                    email=email,
                    password=user.password,
                    current_step='email_verification',
                    nto_campaign_slug=_registration_nto_slug(request),
                )
                new_attempt.generate_email_code()
                send_email_verification_code(new_attempt)
                login(request, user)
                return redirect(reverse('verify_email'))
    else:
        form = RegistrationForm()

    return render(request, 'registration/register_initial.html', {
        'form': form,
        'password_help': password_validators_help_text_html(),
        'nto_campaign_slug': _registration_nto_slug(request),
    })


COOLDOWN_SECONDS = 10

@ensure_registration_gate('registration_step')
def verify_email(request):
    attempt = request.user.registrationpersonaldata

    if not attempt.email_verification_code or attempt.is_email_code_expired():
        attempt.generate_email_code()
        try:
            from .services.email_service import send_email_verification_code
            send_email_verification_code(attempt)
            messages.success(request, 'Мы отправили ссылку для подтверждения на вашу почту.')
        except Exception as e:
            print('error', e)
            messages.error(request, 'Не удалось отправить письмо. Попробуйте ещё раз позже.')

    can_resend_at = None
    can_resend_now = True
    if attempt.email_code_sent_at:
        can_resend_at = attempt.email_code_sent_at + timedelta(seconds=COOLDOWN_SECONDS)
        can_resend_now = timezone.now() >= can_resend_at

    return render(request, 'registration/verify_email.html', {
        'email': attempt.email,
        'can_resend_now': can_resend_now,
        'can_resend_at': can_resend_at,
        'cooldown_seconds': COOLDOWN_SECONDS,
    })

def resend_email_code(request):
    attempt = request.user.registrationpersonaldata

    if attempt.email_code_sent_at:
        next_allowed_time = attempt.email_code_sent_at + timedelta(seconds=COOLDOWN_SECONDS)
        if timezone.now() < next_allowed_time:
            wait_left = int((next_allowed_time - timezone.now()).total_seconds())
            messages.warning(request, f'Слишком часто. Можно отправить новый код через {wait_left} сек.')
            return redirect(reverse('verify_email'))

    attempt.generate_email_code()

    try:
        send_email_verification_code(attempt)
        messages.success(request, 'Новый код отправлен. Пожалуйста, проверьте почту (и папку «Спам»).')
    except Exception as e:
        print('error', e)
        messages.error(request, 'Не удалось отправить письмо. Попробуйте ещё раз чуть позже.')

    return redirect(reverse('verify_email'))

def verify_email_confirm(request, token):
    attempt = (
        RegistrationPersonalData.objects
        .filter(email_verification_code=token)
        .first()
    )

    if not attempt:
        return redirect(reverse('login'))

    if attempt.email_verified:
        return redirect(reverse('connect_telegram'))

    if attempt.is_email_code_expired():
        attempt.email_verification_code = None
        attempt.save(update_fields=['email_verification_code'])
        messages.error(request, 'Ссылка истекла. Отправили новую.')
        return redirect(reverse('verify_email'))

    with transaction.atomic():
        attempt.email_verified = True
        attempt.current_step = 'telegram_connection'
        attempt.email_verification_code = None
        attempt.save(update_fields=['email_verified', 'current_step', 'email_verification_code'])

    login(request, attempt.user)
    messages.success(request, 'Email подтвержден.')
    logger.info('Email подтвержден.')
    return redirect(reverse('connect_telegram'))

@ensure_registration_gate('registration_step')
def connect_telegram(request):
    attempt = request.user.registrationpersonaldata

    bot_username = config.TG_BOT_USERS_USERNAME
    activation_token = attempt.telegram_account.activation_token
    telegram_bot_link = f"https://t.me/{bot_username}?start=activate_{activation_token}"

    if request.method == 'POST':
        attempt.telegram_account.refresh_from_db()

        if attempt.telegram_account.telegram_verified:
            attempt.current_step = 'finish'
            attempt.save(update_fields=['current_step'])
            return redirect(reverse('finish_registration'))

        return render(request, 'registration/connect_telegram.html', {
            'telegram_bot_link': telegram_bot_link,
            'is_telegram_account_active_web': False,
            'error_message': 'Пожалуйста, сначала нажмите Start у бота и дождитесь привязки аккаунта.'
        })

    is_verified = attempt.telegram_account.telegram_verified
    return render(request, 'registration/connect_telegram.html', {
        'telegram_bot_link': telegram_bot_link,
        'is_telegram_account_active_web': is_verified
    })


@login_required
@ensure_registration_gate('protected')
@require_http_methods(["GET", "POST"])
def connect_telegram_after_registration(request):
    telegram_account, _ = TelegramAccount.objects.get_or_create(user=request.user)

    if request.method == "GET":
        return redirect(reverse('personal_info'))

    if not telegram_account.activation_token:
        telegram_account.activation_token = uuid.uuid4()
        telegram_account.save(update_fields=['activation_token'])

    telegram_account.refresh_from_db()
    if telegram_account.telegram_id:
        messages.success(request, 'Мессенджер привязан.')
    else:
        messages.warning(request, 'Сначала нажмите «Привязать», запустите бота и поделитесь номером телефона.')
    return redirect(reverse('personal_info'))


@login_required
@require_http_methods(["GET", "POST"])
def skip_telegram(request):
    attempt = request.user.registrationpersonaldata
    if attempt.current_step == 'phone_verification_needed':
        return redirect(reverse('verify_phone_if_needed'))
    if attempt.current_step != 'telegram_connection':
        return redirect(reverse('redirect_to_current_step'))

    attempt.current_step = 'phone_verification_needed'
    attempt.save(update_fields=['current_step'])
    return redirect(reverse('verify_phone_if_needed'))


@ensure_registration_gate('registration_step')
def verify_phone_if_needed(request):
    attempt = request.user.registrationpersonaldata

    if attempt.current_step == 'wait_for_call':
        return redirect(reverse('wait_for_phone_call'))

    if request.method == 'POST':
        form = PhoneNumberForm(request.POST)
        if form.is_valid():
            phone = form.cleaned_data['phone']
            pincode = f"{random.randint(1000, 9999)}"

            api_resp = initiate_zvonok_verification(phone, pincode=pincode)
            ok = False
            err_msg = None
            if isinstance(api_resp, dict):
                ok = api_resp.get('ok', bool(api_resp))
                err_msg = api_resp.get('message')
            else:
                ok = bool(api_resp)
            if ok:
                attempt.phone = phone
                attempt.user.user_info.phone = phone
                attempt.current_step = 'wait_for_call'
                attempt.save(update_fields=['phone', 'current_step'])

                user_info = request.user.user_info
                if user_info:
                    user_info.phone = phone
                    user_info.save(update_fields=['phone'])

                return redirect(reverse('wait_for_phone_call'))

            logger.error(err_msg)
            form.add_error(None, err_msg or 'Не удалось инициировать проверку звонком. Попробуйте ещё раз.')
    else:
        form = PhoneNumberForm()

    return render(request, 'registration/enter_phone_number.html', {'form': form})


def wait_for_phone_call(request):
    attempt = request.user.registrationpersonaldata
    return render(request, 'registration/wait_for_phone_call.html', {
        'phone': attempt.phone,
    })


def check_phone_call_status(request):
    attempt = request.user.registrationpersonaldata

    if not attempt or not attempt.phone:
        return JsonResponse({'status': 'error', 'message': 'Незавершенная регистрация не найдена.'}, status=400)

    api_resp = poll_zvonok_status(attempt.phone)
    if api_resp is None or api_resp is False:
        return JsonResponse({'status': 'error', 'message': 'Ошибка API zvonok.com.'}, status=502)

    dial_status = None
    if isinstance(api_resp, dict):
        dial_status = api_resp.get('dial_status_display')

    SUCCESS_STATUSES = {'Абонент ответил'}
    if dial_status in SUCCESS_STATUSES:
        with transaction.atomic():
            attempt.phone_verified = True
            attempt.user.user_info.phone = attempt.phone
            attempt.user.user_info.save()
            attempt.current_step = 'finish'
            attempt.save(update_fields=['phone_verified', 'current_step'])

            user = attempt.user
            if user and not user.is_active:
                user.is_active = True
                user.save(update_fields=['is_active'])

            tg = attempt.telegram_account
            if tg and not tg.telegram_verified:
                tg.telegram_verified = True
                tg.activation_token = None
                tg.save(update_fields=['telegram_verified', 'activation_token'])
        logger.info('Номер телефона подтверждён.')
        return JsonResponse({'status': 'success', 'message': 'Номер телефона успешно подтвержден!'})

    return JsonResponse({
        'status': 'pending',
        'message': 'Ожидание звонка',
        'dial_status': dial_status
    })


def change_phone_number(request):
    attempt = request.user.registrationpersonaldata
    attempt.phone = None
    attempt.current_step = 'phone_verification_needed'
    attempt.save(update_fields=['phone', 'current_step'])
    return redirect(reverse('verify_phone_if_needed'))

def return_to_telegram_connection(request):
    attempt = request.user.registrationpersonaldata
    attempt.current_step = 'telegram_connection'
    attempt.save(update_fields=['current_step'])
    return redirect(reverse('connect_telegram'))

@ensure_registration_gate('registration_step')
def finish_registration(request):
    attempt = request.user.registrationpersonaldata

    user = attempt.user
    if user and not user.is_active:
        user.is_active = True
        user.save(update_fields=['is_active'])

    login(request, user)

    return render(request, 'registration/registration_complete.html', {'user': user, 'nto_campaign_slug': attempt.nto_campaign_slug})

@ensure_registration_gate('protected')
@require_selection_step(UserInfo.SelectionStep.ML)
@login_required
def motivation_letter(request):
    user = request.user
    instruction = MotivationLetterInstruction.get_current()
    letter = None
    is_new_letter = True

    try:
        letter = MotivationLetter.objects.get(user=user)
        is_new_letter = False
    except MotivationLetter.DoesNotExist:
        letter = MotivationLetter.objects.create(user=user)

    if request.method == 'POST':
        if letter and letter.status == MotivationLetter.Status.SUBMITTED:
            messages.warning(request, 'Письмо уже отправлено и не может быть отредактировано.')
            return redirect('motivation_letter')

        form = MotivationLetterForm(request.POST, instance=letter)

        if form.is_valid():
            saved_letter = form.save(commit=False)

            if is_new_letter:
                saved_letter.user = user
            else:
                original_letter_instance = MotivationLetter.objects.get(pk=letter.pk)
                if not original_letter_instance.admin_rating:
                    saved_letter.gpt_review = None

            if 'submit' in request.POST:
                saved_letter.status = MotivationLetter.Status.SUBMITTED
                saved_letter.submitted_at = datetime.now()

                try:
                    saved_letter.full_clean()
                    saved_letter.save()
                    messages.success(request, 'Письмо отправлено. Дальнейшее редактирование невозможно.')
                    logger.info('Мотивационное письмо отправлено пользователем %s', user.pk)
                    return redirect('motivation_letter')
                except Exception as e:
                    form.add_error(None, e)
                    messages.error(request, 'Не удалось отправить письмо. Проверьте ошибки.')
            else:
                saved_letter.status = MotivationLetter.Status.DRAFT
                saved_letter.save()
                messages.success(request, 'Черновик успешно сохранён!')
                logger.info('Черновик мотивационного письма сохранён пользователем %s', user.pk)
                return redirect('motivation_letter')
        else:
            messages.error(request, 'Пожалуйста, исправьте ошибки в форме.')
    else:
        form = MotivationLetterForm(instance=letter)

    return render(request, 'MotivationLetter/motivation_letter.html', {
        'form': form,
        'is_new_letter': is_new_letter,
        'user': user,
        'letter': letter,
        'instruction': instruction,
        'active': 'motivation_letter',
    })


@login_required
@require_POST
def motivation_letter_autosave(request):
    user = request.user
    text = (request.POST.get("letter_text") or "").strip()

    letter, created = MotivationLetter.objects.get_or_create(
        user=user,
        defaults={
            "letter_text": text,
            "status": MotivationLetter.Status.DRAFT,
        },
    )

    if letter.status == MotivationLetter.Status.SUBMITTED:
        return HttpResponse("Письмо уже отправлено — автосохранение отключено.", status=400)
    if letter.admin_rating:
        return HttpResponse("Письмо уже оценено администратором — редактирование запрещено.", status=400)

    letter.letter_text = text
    letter.status = MotivationLetter.Status.DRAFT

    try:
        letter.full_clean()
        letter.save(update_fields=["letter_text", "status"])
    except Exception as e:
        return HttpResponse(f"Ошибка сохранения: {e}", status=400)

    saved_at = timezone.localtime().strftime("%H:%M:%S")
    return HttpResponse(f"Черновик сохранён в {saved_at}")


@ensure_registration_gate('protected')
@login_required
def notification_list(request):
    user_notifications = UserNotification.objects.filter(recipient=request.user).order_by('is_seen',
                                                                                          '-notification__created_at')

    return render(request, 'notifications/notifications_list.html', {'notifications': user_notifications})


@login_required
@require_POST
def mark_notification_as_seen(request, user_notification_id):
    notification = get_object_or_404(UserNotification, pk=user_notification_id, recipient=request.user)

    if not notification.is_seen:
        notification.is_seen = True
        notification.seen_at = timezone.now()
        notification.save()
        logger.info(f'Оповещение {notification.pk} прочитано')

    return redirect('notifications')


@staff_member_required
def send_notification_to_users(request):
    selected_user_ids = request.session.get('selected_users_for_notification', [])

    if not selected_user_ids:
        messages.error(request, "Не выбраны пользователи для отправки оповещения.")
        return redirect('admin:auth_user_changelist')

    selected_users = User.objects.filter(id__in=selected_user_ids)

    if request.method == 'POST':
        form = SendNotificationForm(request.POST)
        if form.is_valid():
            message_text = form.cleaned_data['message']

            with transaction.atomic():
                new_notification = Notification.objects.create(message=message_text, sender=request.user)

                user_notification_objects = [
                    UserNotification.objects.create(notification=new_notification, recipient=user)
                    for user in selected_users
                ]
                # UserNotification.objects.bulk_create(user_notification_objects)

            logger.info(f'Массовое оповещение {new_notification.pk} зарегистрировано')
            messages.success(request, f"Оповещение '{message_text[:30]}...' успешно отправлено {len(selected_user_ids)} пользователям.")
            del request.session['selected_users_for_notification']
            return redirect('admin:auth_user_changelist')
    else:
        form = SendNotificationForm()

    context = {
        'form': form,
        'title': f"Отправить оповещение {len(selected_user_ids)} выбранным пользователям",
        'users': selected_users,
        'opts': User._meta,
        'app_label': 'auth',
    }
    return render(request, 'admin/toManyNotifications.html', context)


@login_required
def notifications_dropdown(request):
    items = (
        UserNotification.objects
        .select_related('notification')
        .filter(recipient=request.user, is_seen=False)
        .order_by('-notification__created_at')[:20]
    )
    return render(request, 'notifications/_dropdown_items.html', {'items': items})


