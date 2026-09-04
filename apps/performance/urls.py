from django.urls import path
from . import views
urlpatterns = [path("reports/", views.reports, name="reports"), path("alerts/", views.alerts, name="alerts"), path("alerts/<int:pk>/<str:status>/", views.alert_status, name="alert_status")]
