from django import forms

# ✅ Add this widget to allow multiple files
class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class TicketCreateForm(forms.ModelForm):
    class Meta:
        from .models import Ticket
        model = Ticket
        fields = ["subject", "description", "topic", "priority"]

class TicketReplyForm(forms.Form):
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    is_internal = forms.BooleanField(required=False, initial=False)
    # ✅ Use the custom widget here
    attachments = forms.FileField(widget=MultiFileInput(), required=False)

class TicketAssignForm(forms.Form):
    status = forms.ChoiceField(choices=[("open","Open"),("pending","Pending"),("waiting","Waiting"),("solved","Solved"),("closed","Closed")])
    priority = forms.ChoiceField(choices=[("low","Low"),("normal","Normal"),("high","High"),("urgent","Urgent")])
    assignee_id = forms.IntegerField(required=False)
