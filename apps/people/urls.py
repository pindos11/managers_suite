from django.urls import path
from . import views

urlpatterns = [path("", views.employees, name="employees"), path("new/", views.employee_edit, name="employee_new"), path("<int:pk>/", views.employee_edit, name="employee_edit"), path("locations/", views.locations, name="locations"), path("locations/new/", views.location_edit, name="location_new"), path("locations/<int:pk>/", views.location_edit, name="location_edit")]
