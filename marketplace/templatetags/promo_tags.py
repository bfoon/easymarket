from django import template
from django.utils import timezone
from stores.models import PromotionCampaign

register = template.Library()

@register.simple_tag
def get_live_promotions(placement, limit=10):
    now = timezone.now()
    return (PromotionCampaign.objects
            .filter(placement=placement,
                    status__in=[PromotionCampaign.Status.APPROVED, PromotionCampaign.Status.LIVE],
                    scheduled_at__lte=now,
                    expires_at__gt=now)
            .select_related("store")
            .order_by("-status", "-scheduled_at")[:limit])
