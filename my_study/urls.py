from django.urls import path
from . import views

app_name = "study"

urlpatterns = [
    path("preparation/add/", views.add_preparation, name="add_preparation"),
    path("preparation/<int:pk>/update/", views.update_preparation, name="update_preparation"),
    path("preparation/<int:pk>/delete/", views.delete_preparation, name="delete_preparation"),
    path("schools/", views.schools_and_courses, name="schools"),
    path("courses/<int:course_id>/select/", views.select_course, name="select_course"),
    path("courses/<int:course_id>/unselect/", views.unselect_course, name="unselect_course"),
    path("universities/", views.universities, name="universities"),
    path("universities/<int:pk>/delete/", views.delete_university_priority, name="delete_university_priority"),
    path("assessments/", views.assessments, name="assessments"),
]
