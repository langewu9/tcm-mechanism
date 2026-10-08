from django import forms
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from apps.core.services.account_identity import users_with_email


class UniqueEmailMixin:
    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and users_with_email(email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("该邮箱已登记，请使用其他邮箱。")
        return email


class ResearcherUserChangeForm(UniqueEmailMixin, UserChangeForm):
    pass


class ResearcherUserCreationForm(UniqueEmailMixin, AdminUserCreationForm):
    pass
