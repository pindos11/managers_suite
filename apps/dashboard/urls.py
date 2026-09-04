from django.urls import path
from . import views
urlpatterns = [path("", views.dashboard, name="dashboard"), path("health/", views.health, name="health")]
