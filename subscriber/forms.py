from django import forms
from .models import EmailSubscriber

class EmailSubscriberForm(forms.Form):
    email = forms.EmailField(
        error_messages={'required': 'Укажи почту, на которую прислать уведомление.', 'invalid': 'Проверь адрес почты. Например: name@example.ru.'},
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "you@example.com",
            "autocomplete": "email",
            "required": True,
            "aria-describedby": "email-hint",
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound and self.errors.get('email'):
            self.fields['email'].widget.attrs.update({'aria-invalid': 'true', 'aria-describedby': 'email-hint email-error', 'class': 'form-control is-invalid'})
