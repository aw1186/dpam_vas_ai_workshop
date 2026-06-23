from django import forms

from .models import Chat, Control, Message, Note, Report, Validation


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ["id", "fund", "isin", "type", "period", "lang", "status"]
        widgets = {
            "period": forms.TextInput(attrs={"placeholder": "YYYY-MM-DD"}),
        }

    def __init__(self, *args, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        if editing:
            self.fields["id"].disabled = True
            self.fields["id"].required = False


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["type", "text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 2})}


class ControlForm(forms.ModelForm):
    class Meta:
        model = Control
        fields = ["control_id", "name", "descr", "status"]


class ValidationForm(forms.ModelForm):
    class Meta:
        model = Validation
        fields = ["team", "state", "signed_by", "signed_at"]


class ChatForm(forms.ModelForm):
    class Meta:
        model = Chat
        fields = ["name", "sub"]


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["text"]
        widgets = {
            "text": forms.TextInput(attrs={"placeholder": "Type a message…"}),
        }
