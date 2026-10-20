from django.conf import settings
from django.db import models


class ResearcherProfile(models.Model):
    """Account verification state separate from platform approval."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="researcher_profile",
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self) -> str:
        return f"Researcher account #{self.user_id}"
