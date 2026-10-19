from django.urls import path

from . import staff_views

app_name = "nto_staff"

urlpatterns = [
    path("", staff_views.queue, name="queue"),
    path("<slug:slug>/applications/<int:application_id>/", staff_views.detail, name="detail"),
    path("<slug:slug>/applications/<int:application_id>/note/", staff_views.save_note, name="save_note"),
    path("<slug:slug>/applications/<int:application_id>/edit/", staff_views.edit, name="edit"),
    path("<slug:slug>/applications/<int:application_id>/<slug:action_name>/", staff_views.action, name="action"),
    path("<slug:slug>/export.xlsx", staff_views.export, name="export"),
    path("<slug:slug>/profiles/import/", staff_views.profile_import, name="profile_import"),
    path("<slug:slug>/profiles/template.xlsx", staff_views.profile_template, name="profile_template"),
    path("<slug:slug>/profiles/export.xlsx", staff_views.profile_export, name="profile_export"),
    path("<slug:slug>/profiles/import/<int:batch_id>/confirm/", staff_views.confirm_import, name="confirm_import"),
]
