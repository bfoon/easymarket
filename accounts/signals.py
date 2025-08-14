from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from accounts.models import AdminLog
from marketplace.models import Product
from reviews.models import Review
from stores.models import Store
from orders.models import CustomerComplaint
from allauth.account.signals import user_signed_up

User = get_user_model()

# ✅ Product Add/Edit (with field difference logging)
@receiver(post_save, sender=Product)
def log_product_create_or_update(sender, instance, created, **kwargs):
    user = getattr(instance, '_log_user', None)
    if not user:
        return

    if created:
        AdminLog.objects.create(
            action_type='product_add',
            related_model='Product',
            related_object_id=str(instance.id),
            message=f"New product added: {instance.name}",
            created_by=user
        )
    else:
        updated_fields = getattr(instance, '_changed_fields', [])
        diffs = []
        for field in updated_fields:
            try:
                original = sender.objects.get(pk=instance.pk)
                old = getattr(original, field, None)
                new = getattr(instance, field, None)
                if old != new:
                    diffs.append(f"{field}: '{old}' → '{new}'")
            except sender.DoesNotExist:
                continue

        if diffs:
            AdminLog.objects.create(
                action_type='product_edit',
                related_model='Product',
                related_object_id=str(instance.id),
                message=f"Product '{instance.name}' updated:\n" + "\n".join(diffs),
                created_by=user
            )

# ✅ Product Deletion
@receiver(post_delete, sender=Product)
def log_product_delete(sender, instance, **kwargs):
    user = getattr(instance, '_log_user', None)
    if not user:
        return

    AdminLog.objects.create(
        action_type='product_delete',
        related_model='Product',
        related_object_id=str(instance.id),
        message=f"Deleted product: {instance.name}",
        created_by=user
    )

# ✅ Store Settings Updated
@receiver(post_save, sender=Store)
def log_store_edit(sender, instance, created, **kwargs):
    if not created:
        user = getattr(instance, '_log_user', None)
        if not user:
            return

        AdminLog.objects.create(
            action_type='store_edit',
            related_model='Store',
            related_object_id=str(instance.id),
            message=f"Store '{instance.name}' settings updated.",
            created_by=user
        )

# ✅ Bad Product Rating Detection (1 or 2 stars)
@receiver(post_save, sender=Review)
def log_bad_rating(sender, instance, created, **kwargs):
    if created and instance.rating <= 2:
        AdminLog.objects.create(
            action_type='bad_rating',
            related_model='Review',
            related_object_id=str(instance.id),
            message=f"Bad rating ({instance.rating}) for product '{instance.product.name}'",
            created_by=instance.user
        )

# ✅ Customer Complaint Logged
@receiver(post_save, sender=CustomerComplaint)
def log_customer_complaint(sender, instance, created, **kwargs):
    if created:
        AdminLog.objects.create(
            action_type='complaint',
            related_model='CustomerComplaint',
            related_object_id=str(instance.id),
            message=f"New complaint from {instance.customer.get_full_name()}",
            created_by=instance.customer
        )
@receiver(user_signed_up)
def after_social_signup(request, user, **kwargs):
    # Set any defaults you want on social sign-up
    if not user.username:
        from django.utils.crypto import get_random_string
        base = (user.email.split("@")[0] if user.email else "user")[:20] or get_random_string(8).lower()
        user.username = base
        user.save()