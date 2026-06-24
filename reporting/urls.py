from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    # Reports
    path("reports/", views.reports_list, name="reports"),
    path("reports/new/", views.report_create, name="report_create"),
    path("reports/<str:pk>/", views.report_detail, name="report_detail"),
    path("reports/<str:pk>/edit/", views.report_edit, name="report_edit"),
    path("reports/<str:pk>/delete/", views.report_delete, name="report_delete"),
    path("reports/<str:pk>/status/", views.report_set_status, name="report_set_status"),
    path("reports/<str:pk>/validation/<int:vid>/", views.validation_set, name="validation_set"),
    path("reports/<str:pk>/note/", views.note_add, name="note_add"),
    path("reports/<str:pk>/note/<int:nid>/delete/", views.note_delete, name="note_delete"),

    # Controls
    path("controls/", views.controls_view, name="controls"),

    # Chat
    path("chat/", views.chat_view, name="chat"),
    path("chat/new/", views.chat_create, name="chat_create"),
    path("chat/<str:chat_id>/", views.chat_view, name="chat_detail"),
    path("chat/<str:chat_id>/send/", views.chat_send, name="chat_send"),
    path("chat/<str:chat_id>/delete/", views.chat_delete, name="chat_delete"),

    # Database admin
    path("database/", views.database_view, name="database"),
    path("database/reset/", views.database_reset, name="database_reset"),
    path("database/<str:table>/", views.database_view, name="database_table"),
    path("database/<str:table>/new/", views.database_form, name="database_create"),
    path("database/<str:table>/<path:pk>/edit/", views.database_form, name="database_edit"),
    path("database/<str:table>/<path:pk>/delete/", views.database_delete, name="database_delete"),

    # FundLink (Oracle data warehouse)
    path("fundlink/", views.fundlink_view, name="fundlink"),
]
