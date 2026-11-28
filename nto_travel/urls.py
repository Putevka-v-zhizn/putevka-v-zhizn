from django.urls import path

from . import views

app_name = "nto_travel"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("<slug:slug>/apply/<slug:step>/", views.apply_step, name="apply_step"),
    path("<slug:slug>/review/", views.review, name="review"),
    path("<slug:slug>/submit/", views.submit, name="submit"),
    path("<slug:slug>/application/", views.application, name="application"),
]
