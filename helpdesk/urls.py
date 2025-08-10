from django.urls import path
from . import views

app_name = "helpdesk"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/new/", views.ticket_create, name="ticket_create"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/reply/", views.ticket_reply, name="ticket_reply"),
    path("tickets/<int:pk>/assign/", views.ticket_assign_update, name="ticket_assign_update"),
]
