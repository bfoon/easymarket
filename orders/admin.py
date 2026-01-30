from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    PromoCode, Order, OrderItem, ShippingAddress,
    Return, ReturnItem, ReturnRefund,
    OrderStatusHistory, ReturnStatusHistory, ReturnImage,
    StoreInventory, ChatMessage
)
from logistics.models import OrderLogisticsAgent, LogisticsAgentMessage
from django.urls import reverse
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'price_at_time')


class ReturnItemInline(admin.TabularInline):
    model = ReturnItem
    extra = 0


class ReturnImageInline(admin.TabularInline):
    model = ReturnImage
    extra = 0


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    """Admin interface for PromoCode model"""

    list_display = [
        'code_display',
        'discount_display',
        'source',
        'usage_display',
        'status_display',
        'valid_until',
        'is_active'
    ]

    list_filter = [
        'source',
        'discount_type',
        'is_active',
        'first_purchase_only',
        'created_at',
        ('valid_until', admin.DateFieldListFilter),
    ]

    search_fields = [
        'code',
        'description',
        'campaign__name',
    ]

    readonly_fields = [
        'usage_count',
        'created_at',
        'updated_at',
        'usage_progress',
        'days_remaining',
    ]

    raw_id_fields = ['campaign', 'created_by']

    filter_horizontal = [
        'allowed_users',
        'excluded_users',
        'valid_for_products',  # Changed from 'applicable_products'
        'valid_for_categories'  # Changed from 'applicable_categories'
    ]

    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Information', {
            'fields': (
                'code',
                'description',
                'source',
                'is_active'
            )
        }),
        ('Discount Configuration', {
            'fields': (
                'discount_type',
                'discount_value',
                'min_purchase_amount'
            )
        }),
        ('Usage & Limits', {
            'fields': (
                'max_uses',
                'usage_count',
                'usage_progress',
                'first_purchase_only'
            )
        }),
        ('Validity Period', {
            'fields': (
                'valid_from',
                'valid_until',
                'days_remaining'
            )
        }),
        ('Campaign Association', {
            'fields': ('campaign',),
            'classes': ('collapse',),
            'description': 'Link to campaign (automatically set for wheel prizes)'
        }),
        ('User Restrictions', {
            'fields': (
                'allowed_users',
                'excluded_users'
            ),
            'classes': ('collapse',),
            'description': 'Restrict code to specific users'
        }),
        ('Product/Category Restrictions', {
            'fields': (
                'valid_for_products',  # Changed
                'valid_for_categories'  # Changed
            ),
            'classes': ('collapse',),
            'description': 'Limit code to specific products or categories'
        }),
        ('Metadata', {
            'fields': (
                'created_by',
                'created_at',
                'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )

    # Custom display methods

    def code_display(self, obj):
        """Display code with wheel indicator"""
        if obj.source == 'campaign_wheel':
            return format_html(
                '<strong>🎡 {}</strong>',
                obj.code
            )
        return obj.code

    code_display.short_description = 'Code'
    code_display.admin_order_field = 'code'

    def discount_display(self, obj):
        """Display discount value with type"""
        if obj.discount_type == 'percentage':
            return f"{obj.discount_value}% off"
        elif obj.discount_type == 'fixed':
            return f"D{obj.discount_value} off"
        elif obj.discount_type == 'free_shipping':
            return "Free Shipping"
        return "-"

    discount_display.short_description = 'Discount'

    def usage_display(self, obj):
        """Display usage with progress"""
        if obj.max_uses:
            percentage = (obj.uses / obj.max_uses * 100) if obj.max_uses > 0 else 0
            if percentage >= 100:
                color = 'red'
            elif percentage >= 75:
                color = 'orange'
            else:
                color = 'green'

            return format_html(
                '<span style="color: {};">{} / {}</span>',
                color,
                obj.uses,
                obj.max_uses
            )
        return f"{obj.uses} (unlimited)"

    usage_display.short_description = 'Usage'
    usage_display.admin_order_field = 'uses'

    def status_display(self, obj):
        """Display current status"""
        now = timezone.now()

        if not obj.is_active:
            return format_html('<span style="color: red;">❌ Inactive</span>')

        if obj.valid_until and now > obj.valid_until:
            return format_html('<span style="color: red;">⏰ Expired</span>')

        if obj.max_uses and obj.uses >= obj.max_uses:
            return format_html('<span style="color: orange;">📊 Fully Used</span>')

        if obj.valid_from and now < obj.valid_from:
            return format_html('<span style="color: blue;">🕐 Scheduled</span>')

        # Check if wheel prize is redeemed
        if obj.source == 'campaign_wheel':
            if hasattr(obj, 'wheel_spin') and obj.wheel_spin:
                if obj.wheel_spin.is_redeemed:
                    return format_html('<span style="color: green;">✅ Redeemed</span>')

        return format_html('<span style="color: green;">✅ Active</span>')

    status_display.short_description = 'Status'

    def usage_progress(self, obj):
        """Show usage progress bar"""
        if not obj.max_uses:
            return "Unlimited"

        percentage = (obj.uses / obj.max_uses * 100) if obj.max_uses > 0 else 0

        if percentage >= 100:
            color = '#d32f2f'
        elif percentage >= 75:
            color = '#f57c00'
        elif percentage >= 50:
            color = '#fbc02d'
        else:
            color = '#388e3c'

        return format_html(
            '<div style="width: 100%; background-color: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background-color: {}; height: 20px; border-radius: 3px; '
            'text-align: center; color: white; font-size: 11px; line-height: 20px;">'
            '{}%</div></div>',
            min(percentage, 100),
            color,
            int(percentage)
        )

    usage_progress.short_description = 'Usage Progress'

    def days_remaining(self, obj):
        """Show days until expiration"""
        if not obj.valid_until:
            return "No expiration"

        days = obj.days_until_expiry
        if days == 0:
            return format_html('<span style="color: red;">Expires today!</span>')
        elif days < 0:
            return format_html('<span style="color: red;">Expired</span>')
        elif days <= 7:
            return format_html('<span style="color: orange;">{} days</span>', days)
        else:
            return f"{days} days"

    days_remaining.short_description = 'Days Remaining'

    # Admin actions

    actions = [
        'activate_codes',
        'deactivate_codes',
        'reset_usage',
    ]

    def activate_codes(self, request, queryset):
        """Activate selected promo codes"""
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} promo code(s) activated.")

    activate_codes.short_description = "Activate selected codes"

    def deactivate_codes(self, request, queryset):
        """Deactivate selected promo codes"""
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} promo code(s) deactivated.")

    deactivate_codes.short_description = "Deactivate selected codes"

    def reset_usage(self, request, queryset):
        """Reset usage counter (use with caution!)"""
        count = queryset.update(uses=0)
        self.message_user(
            request,
            f"{count} promo code(s) usage reset. Use this action carefully!",
            level='WARNING'
        )

    reset_usage.short_description = "Reset usage counter (careful!)"

    def get_queryset(self, request):
        """Optimize queries"""
        qs = super().get_queryset(request)
        return qs.select_related('campaign', 'created_by').prefetch_related(
            'wheel_spin',
            'allowed_users',
            'excluded_users',
        )

    def save_model(self, request, obj, form, change):
        """Set created_by if not set"""
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'buyer', 'status', 'created_at', 'get_total', 'promo_code')
    list_filter = ('status', 'created_at')
    search_fields = ('id', 'buyer__username', 'tracking_number')
    inlines = [OrderItemInline]
    readonly_fields = ('created_at', 'updated_at', 'shipped_date', 'delivered_date', 'payment_date')


@admin.register(OrderItem)

class OrderItemAdmin(admin.ModelAdmin):
    list_display = [
        'product',
        'order',
        'quantity',
        'shipped_to_warehouse',
        'shipped_at',
        'current_shipment'
    ]
    list_filter = ['shipped_to_warehouse', 'created_at']
    search_fields = ['product__name', 'order__id']
    readonly_fields = ['shipped_at', 'created_at']  # Make shipped_at readonly

    fieldsets = (
        ('Basic Information', {
            'fields': ('order', 'product', 'quantity', 'price_at_time')
        }),
        ('Discount', {
            'fields': ('discount_type', 'discount_value')
        }),
        ('Warehouse Shipping', {
            'fields': ('shipped_to_warehouse', 'shipped_at', 'current_shipment'),
            'description': 'shipped_at is automatically set when shipped_to_warehouse becomes True'
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        })
    )

@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('order', 'status', 'changed_by', 'timestamp')
    list_filter = ('status', 'timestamp')
    search_fields = ('order__id', 'changed_by__username')


@admin.register(ShippingAddress)
class ShippingAddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'city', 'region', 'country', 'is_default')
    list_filter = ('is_default', 'country', 'created_at')
    search_fields = ('user__username', 'full_name', 'street', 'city')


@admin.register(Return)
class ReturnAdmin(admin.ModelAdmin):
    list_display = ('return_number', 'order', 'buyer', 'status', 'refund_amount', 'created_at')
    list_filter = ('status', 'logistics_method', 'created_at')
    search_fields = ('return_number', 'order__id', 'buyer__username', 'tracking_number')
    inlines = [ReturnItemInline, ReturnImageInline]
    readonly_fields = ('return_number', 'created_at', 'updated_at', 'approved_at', 'completed_at')


@admin.register(ReturnItem)
class ReturnItemAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'product', 'quantity', 'condition', 'price_at_return')
    list_filter = ('condition',)
    search_fields = ('return_request__return_number', 'product__name')


@admin.register(ReturnRefund)
class ReturnRefundAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'refund_amount', 'refund_method', 'status', 'processed_at')
    list_filter = ('status', 'refund_method', 'processed_at')
    search_fields = ('return_request__return_number',)


@admin.register(ReturnStatusHistory)
class ReturnStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'status', 'changed_by', 'timestamp')
    list_filter = ('status',)
    search_fields = ('return_request__return_number', 'changed_by__username')


@admin.register(ReturnImage)
class ReturnImageAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'image', 'description', 'uploaded_at')
    readonly_fields = ('uploaded_at',)


@admin.register(StoreInventory)
class StoreInventoryAdmin(admin.ModelAdmin):
    list_display = ('store_name', 'regular_stock', 'returned_stock', 'discounted_stock', 'last_updated')
    search_fields = ('store_name',)
    readonly_fields = ('last_updated',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('order', 'sender', 'created_at', 'is_read')
    list_filter = ('is_read', 'created_at')
    search_fields = ('order__id', 'sender__username', 'content')


@admin.register(OrderLogisticsAgent)
class OrderLogisticsAgentAdmin(admin.ModelAdmin):
    """
    Admin interface for managing logistics agent assignments
    """
    list_display = [
        'order_id',
        'agent_name',
        'status_badge',
        'assigned_at',
        'working_duration',
        'is_available',
        'last_activity',
        'action_links'
    ]
    list_filter = [
        'status',
        'is_available',
        'assigned_at',
        'started_working_at'
    ]
    search_fields = [
        'order__id',
        'agent__username',
        'agent__first_name',
        'agent__last_name',
        'agent__email',
        'notes'
    ]
    readonly_fields = [
        'assigned_at',
        'started_working_at',
        'completed_at',
        'last_activity',
        'working_duration_display'
    ]
    fieldsets = (
        ('Assignment Details', {
            'fields': (
                'order',
                'agent',
                'status',
                'is_available'
            )
        }),
        ('Timeline', {
            'fields': (
                'assigned_at',
                'started_working_at',
                'completed_at',
                'last_activity',
                'working_duration_display'
            )
        }),
        ('Additional Information', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    date_hierarchy = 'assigned_at'
    actions = ['mark_as_working', 'mark_as_completed', 'mark_as_paused']

    def agent_name(self, obj):
        """Display agent's full name"""
        if obj.agent:
            return obj.agent.get_full_name() or obj.agent.username
        return "Unassigned"

    agent_name.short_description = 'Agent'

    def status_badge(self, obj):
        """Display status with color coding"""
        colors = {
            'assigned': '#3b82f6',
            'working': '#22c55e',
            'paused': '#f59e0b',
            'completed': '#8b5cf6'
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 12px; '
            'border-radius: 12px; font-size: 12px; font-weight: 600;">{}</span>',
            color,
            obj.get_status_display()
        )

    status_badge.short_description = 'Status'

    def working_duration(self, obj):
        """Display how long agent has been working"""
        if obj.working_duration:
            total_seconds = int(obj.working_duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            if hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"
        return "-"

    working_duration.short_description = 'Duration'

    def working_duration_display(self, obj):
        """Detailed working duration for detail view"""
        if obj.working_duration:
            return str(obj.working_duration)
        return "Not started yet"

    working_duration_display.short_description = 'Working Duration'

    def action_links(self, obj):
        """Quick action links"""
        order_url = reverse('admin:orders_order_change', args=[obj.order.pk])
        return format_html(
            '<a href="{}" class="button">View Order</a>',
            order_url
        )

    action_links.short_description = 'Actions'

    def mark_as_working(self, request, queryset):
        """Admin action to mark agents as working"""
        count = 0
        for assignment in queryset:
            if assignment.status != 'working':
                assignment.start_working()
                count += 1

        self.message_user(
            request,
            f'Successfully marked {count} assignment(s) as working.'
        )

    mark_as_working.short_description = 'Mark selected as Working'

    def mark_as_completed(self, request, queryset):
        """Admin action to mark assignments as completed"""
        count = 0
        for assignment in queryset:
            if assignment.status != 'completed':
                assignment.mark_completed()
                count += 1

        self.message_user(
            request,
            f'Successfully marked {count} assignment(s) as completed.'
        )

    mark_as_completed.short_description = 'Mark selected as Completed'

    def mark_as_paused(self, request, queryset):
        """Admin action to pause assignments"""
        count = 0
        for assignment in queryset:
            if assignment.status != 'paused':
                assignment.pause_work()
                count += 1

        self.message_user(
            request,
            f'Successfully paused {count} assignment(s).'
        )

    mark_as_paused.short_description = 'Mark selected as Paused'


@admin.register(LogisticsAgentMessage)
class LogisticsAgentMessageAdmin(admin.ModelAdmin):
    """
    Admin interface for logistics agent messages
    """
    list_display = [
        'order_id',
        'sender_name',
        'message_preview',
        'has_image',
        'is_read',
        'created_at'
    ]
    list_filter = [
        'is_read',
        'created_at',
        'sender'
    ]
    search_fields = [
        'order__id',
        'sender__username',
        'sender__email',
        'message'
    ]
    readonly_fields = ['created_at', 'order', 'sender']
    date_hierarchy = 'created_at'

    def sender_name(self, obj):
        """Display sender's name"""
        return obj.sender.get_full_name() or obj.sender.username

    sender_name.short_description = 'Sender'

    def message_preview(self, obj):
        """Display message preview"""
        if len(obj.message) > 50:
            return f"{obj.message[:50]}..."
        return obj.message

    message_preview.short_description = 'Message'

    def has_image(self, obj):
        """Display if message has image"""
        if obj.image:
            return format_html(
                '<span style="color: green;">✓ Yes</span>'
            )
        return format_html(
            '<span style="color: gray;">✗ No</span>'
        )

    has_image.short_description = 'Image'


# Optional: Inline admin for adding logistics agent to Order admin
class OrderLogisticsAgentInline(admin.StackedInline):
    """
    Inline form for assigning logistics agent directly from Order admin
    """
    model = OrderLogisticsAgent
    extra = 0
    max_num = 1
    can_delete = True
    fields = ['agent', 'status', 'is_available', 'notes']
    readonly_fields = ['assigned_at', 'started_working_at', 'completed_at']