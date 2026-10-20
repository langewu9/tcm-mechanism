from django.contrib.auth import get_user_model
from django.db.models import Value
from django.db.models.functions import Lower, Trim


def users_with_email(email):
    """Match the expression used by the database's unique nonblank email index."""
    return get_user_model().objects.annotate(
        normalized_email=Lower(Trim("email")),
    ).filter(normalized_email=Lower(Trim(Value(email))))
