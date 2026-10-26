from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from . import program_views
from .views_helper import redirect_to_current_step
from .views_staff import StaffScholarDossierView, staff_scholar_action

urlpatterns = [
    path('', views.index, name='index'),
    path('programs/', program_views.programs, name='programs'),
    path('programs/select/', program_views.program_select, name='program_select'),

    path('register/', views.register_initial, name='register_initial'),
    path('register/verify-email/', views.verify_email, name='verify_email'),
    path('register/verify-email/confirm/<uuid:token>/', views.verify_email_confirm, name='verify_email_confirm'),
    path('register/resend-email-code/', views.resend_email_code, name='resend_email_code'),
    path('register/connect-telegram/', views.connect_telegram, name='connect_telegram'),
    path('register/skip-telegram/', views.skip_telegram, name='skip_telegram'),
    path('register/verify-phone/', views.verify_phone_if_needed, name='verify_phone_if_needed'),
    path('register/complete/', views.finish_registration, name='finish_registration'),

    path('register/wait-for-call/', views.wait_for_phone_call, name='wait_for_phone_call'),
    path('check-call-status/', views.check_phone_call_status, name='check_phone_call_status'),
    path('redirect-registration/', redirect_to_current_step, name='redirect_to_current_step'),
    path('change_phone_number/', views.change_phone_number, name='change_phone_number'),
    path('return_telegram_connection/', views.return_to_telegram_connection, name='return_telegram_connection'),
    path('telegram/connect/', views.connect_telegram_after_registration, name='connect_telegram_after_registration'),

    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='registration/login.html'
    ), name='login'),

    path('accounts/logout/', auth_views.LogoutView.as_view(
        template_name='registration/logout.html'
    ), name='logout'),

    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt',
    ), name='password_reset'),

    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'
    ), name='password_reset_done'),

    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html'
    ), name='password_reset_confirm'),

    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'
    ), name='password_reset_complete'),

    path('motivation/', views.motivation_letter, name='motivation_letter'),
    path("motivation/autosave/", views.motivation_letter_autosave, name="motivation_letter_autosave"),

    path('notifications/dropdown/', views.notifications_dropdown, name='notifications_dropdown'),
    path('notifications/', views.notification_list, name='notifications'),
    path('mark-as-seen/<int:user_notification_id>', views.mark_notification_as_seen, name='mark_as_seen'),

    path("staff/scholars/<int:user_id>/", StaffScholarDossierView.as_view(), name="staff_scholar_dossier"),
    path("staff/scholars/<int:user_id>/action/", staff_scholar_action, name="staff_scholar_action"),

    path("feedback/", views.feedback_view, name="feedback"),
]
