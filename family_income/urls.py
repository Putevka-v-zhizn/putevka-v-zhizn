from django.urls import path

from . import views

app_name = "family_income"

urlpatterns = [
    path("", views.family_income_page, name="page"),
    path("submit/", views.submit_case, name="submit"),
    path("documents/<str:category>/add/", views.add_document, name="add_document"),
    path("documents/<int:document_id>/edit/", views.edit_document, name="edit_document"),
    path("documents/<int:document_id>/delete/", views.delete_document, name="delete_document"),
]
