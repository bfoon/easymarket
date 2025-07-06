def pending_orders_count(request):
    """Context processor to add pending orders count to all templates"""
    if request.user.is_authenticated:
        try:
            pending_count = request.user.orders.filter(status='pending').count()
            return {
                'pending_orders_count': pending_count
            }
        except:
            return {'pending_orders_count': 0}
    return {'pending_orders_count': 0}
