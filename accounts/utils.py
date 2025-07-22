from accounts.models import AdminLog

def log_admin_action(user, action_type, message, model=None, object_id=None):
    if not user.is_authenticated:
        return
    AdminLog.objects.create(
        action_type=action_type,
        related_model=model,
        related_object_id=str(object_id) if object_id else None,
        message=message,
        created_by=user
    )