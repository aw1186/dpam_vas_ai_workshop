from django.contrib import admin

from .models import Chat, Control, Message, Note, Report, Validation


class ControlInline(admin.TabularInline):
    model = Control
    extra = 0


class ValidationInline(admin.TabularInline):
    model = Validation
    extra = 0


class NoteInline(admin.TabularInline):
    model = Note
    extra = 0


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "fund", "type", "period", "lang", "status")
    list_filter = ("status", "lang", "type")
    search_fields = ("id", "fund", "isin")
    inlines = [ControlInline, ValidationInline, NoteInline]


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "sub")
    inlines = [MessageInline]


admin.site.register(Control)
admin.site.register(Validation)
admin.site.register(Note)
admin.site.register(Message)
