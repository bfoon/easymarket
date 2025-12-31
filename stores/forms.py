from django import forms
from marketplace.models import Product, ProductImage, Category, ProductVariant, ProductFeatureOption
from django.core.exceptions import ValidationError
from .models import Store, StoreHours, StoreShippingZone, StoreReturnSettings
import re
from django.core.validators import RegexValidator

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name', 'category', 'price', 'original_price', 'description',
            'specifications', 'image', 'video', 'is_featured', 'is_trending',
            'has_30_day_return', 'free_shipping', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name'
            }),
            'category': forms.Select(attrs={
                'class': 'form-control'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '0.00'
            }),
            'original_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '0.00 (optional)'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter product description'
            }),
            'specifications': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter product specifications'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'video': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'video/*'
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_trending': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'has_30_day_return': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'free_shipping': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()
        self.fields['category'].empty_label = "Select a category"
        self.fields['category'].required = False


class ProductImageForm(forms.ModelForm):
    """Updated form for uploading product images with variant assignment"""

    class Meta:
        model = ProductImage
        fields = ['image', 'alt_text', 'is_primary']
        widgets = {
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'alt_text': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Alternative text for accessibility'
            }),
            'is_primary': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

    def __init__(self, *args, **kwargs):
        product = kwargs.pop('product', None)
        super().__init__(*args, **kwargs)

        # Make all fields optional for formset usage
        self.fields['image'].required = False
        self.fields['alt_text'].required = False
        self.fields['is_primary'].required = False

    def clean(self):
        cleaned_data = super().clean()
        image = cleaned_data.get('image')
        is_primary = cleaned_data.get('is_primary')

        # If no image is provided, skip validation (allows empty forms in formset)
        if not image:
            return cleaned_data

        return cleaned_data


class ProductImageWithVariantsForm(forms.ModelForm):
    """Extended form for existing images with variant assignment"""

    class Meta:
        model = ProductImage
        fields = ['image', 'variants', 'alt_text', 'is_primary']
        widgets = {
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'variants': forms.CheckboxSelectMultiple(attrs={
                'class': 'form-check-input'
            }),
            'alt_text': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Alternative text for accessibility'
            }),
            'is_primary': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

    def __init__(self, *args, **kwargs):
        product = kwargs.pop('product', None)
        super().__init__(*args, **kwargs)

        if product:
            # Only show variants that are actually assigned to this product
            self.fields['variants'].queryset = ProductFeatureOption.objects.filter(
                variants__product=product
            ).distinct().select_related('feature').order_by('feature__name', 'value')
        else:
            self.fields['variants'].queryset = ProductFeatureOption.objects.select_related('feature').order_by(
                'feature__name', 'value')

        # Customize the variant choices display
        self.fields['variants'].label_from_instance = lambda obj: f"{obj.feature.name}: {obj.value}"

    def clean(self):
        cleaned_data = super().clean()
        variants = cleaned_data.get('variants')
        is_primary = cleaned_data.get('is_primary')

        # If marked as primary, should have at least one variant
        if is_primary and variants and not variants.exists():
            self.add_error('is_primary', 'Primary images should have at least one variant assigned.')

        return cleaned_data


class ProductVariantForm(forms.ModelForm):
    """This form is no longer used with the dual-listbox interface but kept for compatibility"""

    class Meta:
        model = ProductVariant
        fields = ['feature_option']
        widgets = {
            'feature_option': forms.Select(attrs={
                'class': 'form-control'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Allow empty extra forms to pass validation
        self.fields['feature_option'].required = False


class ProductWithStockForm(forms.ModelForm):
    quantity = forms.IntegerField(
        label="Stock Quantity",
        min_value=0,
        required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Product
        fields = [
            'name', 'category', 'price', 'original_price', 'description',
            'specifications', 'image', 'video', 'is_featured', 'is_trending',
            'has_30_day_return', 'free_shipping', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name'
            }),
            'category': forms.Select(attrs={
                'class': 'form-control'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '0.00'
            }),
            'original_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '0.00 (optional)'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter product description'
            }),
            'specifications': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter product specifications'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'video': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'video/*'
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_trending': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'has_30_day_return': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'free_shipping': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        stock = kwargs.pop('stock', None)
        super().__init__(*args, **kwargs)

        if stock:
            self.fields['quantity'].initial = stock.quantity

    def save(self, commit=True):
        product = super().save(commit=commit)
        if commit:
            stock, created = product.stock_set.get_or_create(product=product)
            stock.quantity = self.cleaned_data['quantity']
            stock.save()
        return product


class StoreSettingsForm(forms.ModelForm):
    """Comprehensive store settings form"""

    class Meta:
        model = Store
        fields = [
            'name', 'slug', 'description', 'short_description',
            'store_type', 'category', 'email', 'phone', 'website',
            'address_line_1', 'address_line_2', 'city', 'region',
            'postal_code', 'country', 'logo', 'banner',
            'business_registration_number', 'tax_identification_number',
            'commission_rate', 'minimum_order_amount', 'processing_time',
            'return_policy_days', 'facebook_url', 'twitter_url', 'instagram_url',
            'accept_cash_risk', 'allow_referrals'
        ]

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your store name'
            }),
            'slug': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'store-url-slug'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Describe your store and what makes it special...'
            }),
            'short_description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Brief tagline for your store'
            }),
            'store_type': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'store@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+220 123 4567'
            }),
            'website': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://yourwebsite.com'
            }),
            'address_line_1': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Street address'
            }),
            'address_line_2': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Apartment, suite, etc. (optional)'
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'City'
            }),
            'region': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Region/State'
            }),
            'postal_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Postal code'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'value': 'Gambia'
            }),
            'business_registration_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Business registration number'
            }),
            'tax_identification_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tax ID number'
            }),
            'commission_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100'
            }),
            'minimum_order_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'processing_time': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '30'
            }),
            'return_policy_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '365'
            }),
            'facebook_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://facebook.com/yourstore'
            }),
            'twitter_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://twitter.com/yourstore'
            }),
            'instagram_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://instagram.com/yourstore'
            }),
            'accept_cash_risk': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'allow_referrals': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),

        }

    def clean_slug(self):
        slug = self.cleaned_data.get('slug')
        if slug:
            slug = slug.lower().strip()
            if not re.match(r'^[a-z0-9-]+$', slug):
                raise ValidationError('Slug can only contain lowercase letters, numbers, and hyphens.')

            # Check for uniqueness, excluding current instance
            qs = Store.objects.filter(slug=slug)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError('This slug is already taken.')
        return slug

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            # Check for uniqueness, excluding current instance
            qs = Store.objects.filter(email=email)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError('A store with this email already exists.')
        return email


class StoreHoursForm(forms.ModelForm):
    """Form for managing store operating hours"""

    class Meta:
        model = StoreHours
        fields = ['day_of_week', 'opening_time', 'closing_time', 'is_closed']
        widgets = {
            'day_of_week': forms.Select(attrs={'class': 'form-select'}),
            'opening_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'closing_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'is_closed': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

    def clean(self):
        cleaned_data = super().clean()
        is_closed = cleaned_data.get('is_closed')
        opening_time = cleaned_data.get('opening_time')
        closing_time = cleaned_data.get('closing_time')

        if not is_closed:
            if not opening_time or not closing_time:
                raise ValidationError('Opening and closing times are required when the store is open.')
            if opening_time >= closing_time:
                raise ValidationError('Closing time must be after opening time.')

        return cleaned_data


class StoreShippingZoneForm(forms.ModelForm):
    """Form for managing shipping zones"""

    class Meta:
        model = StoreShippingZone
        fields = [
            'name', 'regions', 'base_cost', 'per_kg_cost',
            'free_shipping_threshold', 'estimated_delivery_days', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Greater Banjul Area'
            }),
            'regions': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter regions separated by commas'
            }),
            'base_cost': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'per_kg_cost': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'free_shipping_threshold': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'estimated_delivery_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '30'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }


class StoreReturnSettingsForm(forms.ModelForm):
    """Form for managing return policy settings"""

    class Meta:
        model = StoreReturnSettings
        fields = [
            'return_window_days', 'accept_defective', 'accept_wrong_item',
            'accept_wrong_size', 'accept_damaged_shipping', 'accept_not_as_described',
            'accept_changed_mind', 'accept_quality_issues', 'auto_approve_returns',
            'require_original_packaging', 'require_photos', 'provide_return_label',
            'pickup_service_available', 'restocking_fee_percentage',
            'refund_shipping_cost', 'custom_return_policy'
        ]
        widgets = {
            'return_window_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '365'
            }),
            'restocking_fee_percentage': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100'
            }),
            'custom_return_policy': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter any additional return policy details...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes to boolean fields
        boolean_fields = [
            'accept_defective', 'accept_wrong_item', 'accept_wrong_size',
            'accept_damaged_shipping', 'accept_not_as_described', 'accept_changed_mind',
            'accept_quality_issues', 'auto_approve_returns', 'require_original_packaging',
            'require_photos', 'provide_return_label', 'pickup_service_available',
            'refund_shipping_cost'
        ]

        for field_name in boolean_fields:
            self.fields[field_name].widget.attrs.update({'class': 'form-check-input'})


class StoreFinancialForm(forms.ModelForm):
    """Form for managing store financial settings"""

    class Meta:
        model = Store
        fields = [
            'bank_account_number', 'bank_name', 'commission_rate',
            'minimum_order_amount', 'business_registration_number',
            'tax_identification_number'
        ]
        widgets = {
            'bank_account_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Bank account number'
            }),
            'bank_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Bank name'
            }),
            'commission_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100'
            }),
            'minimum_order_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0'
            }),
            'business_registration_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Business registration number'
            }),
            'tax_identification_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tax identification number'
            }),
        }


# Formset for managing multiple store hours
StoreHoursFormSet = forms.modelformset_factory(
    StoreHours,
    form=StoreHoursForm,
    extra=0,
    can_delete=False
)

# Formset for managing multiple shipping zones
StoreShippingZoneFormSet = forms.modelformset_factory(
    StoreShippingZone,
    form=StoreShippingZoneForm,
    extra=1,
    can_delete=True
)


class StoreReferralForm(forms.Form):
    referred_email = forms.EmailField(label="Friend's Email", widget=forms.EmailInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your friend\'s email'
    }))


class StoreThemeForm(forms.ModelForm):
    """
    Comprehensive form for store theme customization
    """

    class Meta:
        model = Store
        fields = [
            # Theme Selection
            'theme_preset',

            # Color Scheme
            'primary_color',
            'secondary_color',
            'accent_color',
            'background_color',
            'text_color',

            # Typography
            'font_heading',
            'font_body',

            # Layout
            'product_layout',
            'products_per_row',
            'show_product_ratings',
            'show_product_badges',
            'show_quick_view',

            # Store Page Features
            'show_store_description',
            'show_store_stats',
            'show_social_links',
            'show_operating_hours',
            'show_map_location',

            # Social Media
            'facebook_url',
            'instagram_url',
            'twitter_url',
            'linkedin_url',
            'youtube_url',
            'tiktok_url',

            # Header & Banner
            'header_message',
            'show_header_message',
            'banner_overlay_opacity',
            'banner_height',

            # Button Styling
            'cta_button_text',
            'cta_button_style',

            # Product Cards
            'product_card_style',
            'product_image_shape',

            # Animations
            'enable_animations',
            'enable_hover_effects',
            'enable_parallax_banner',

            # Store Sections
            'enable_featured_products',
            'enable_new_arrivals',
            'enable_best_sellers',
            'enable_testimonials',

            # Trust Badges
            'show_secure_checkout_badge',
            'show_free_shipping_badge',
            'show_money_back_guarantee',
            'show_customer_support_badge',

            # Mobile
            'mobile_menu_style',

            # SEO
            'meta_title',
            'meta_description',
            'meta_keywords',

            # Performance
            'enable_lazy_loading',
            'enable_image_optimization',

            # Custom CSS
            'custom_css',
        ]

        widgets = {
            'theme_preset': forms.Select(attrs={
                'class': 'form-select form-control-lg',
                'id': 'themePreset',
            }),

            # Color Pickers
            'primary_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose primary color',
            }),
            'secondary_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose secondary color',
            }),
            'accent_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose accent color',
            }),
            'background_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose background color',
            }),
            'text_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'title': 'Choose text color',
            }),

            # Typography
            'font_heading': forms.Select(attrs={
                'class': 'form-select',
            }),
            'font_body': forms.Select(attrs={
                'class': 'form-select',
            }),

            # Layout
            'product_layout': forms.Select(attrs={
                'class': 'form-select',
            }),
            'products_per_row': forms.Select(attrs={
                'class': 'form-select',
            }),

            # Social Media
            'facebook_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://facebook.com/yourpage',
            }),
            'instagram_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://instagram.com/yourprofile',
            }),
            'twitter_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://twitter.com/yourhandle',
            }),
            'linkedin_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://linkedin.com/company/yourcompany',
            }),
            'youtube_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://youtube.com/c/yourchannel',
            }),
            'tiktok_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://tiktok.com/@yourprofile',
            }),

            # Header Message
            'header_message': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Free shipping on orders over $50!',
                'maxlength': 200,
            }),

            # Banner
            'banner_overlay_opacity': forms.Select(attrs={
                'class': 'form-select',
            }),
            'banner_height': forms.Select(attrs={
                'class': 'form-select',
            }),

            # CTA
            'cta_button_text': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Shop Now',
                'maxlength': 50,
            }),
            'cta_button_style': forms.Select(attrs={
                'class': 'form-select',
            }),

            # Product Card
            'product_card_style': forms.Select(attrs={
                'class': 'form-select',
            }),
            'product_image_shape': forms.Select(attrs={
                'class': 'form-select',
            }),

            # Mobile
            'mobile_menu_style': forms.Select(attrs={
                'class': 'form-select',
            }),

            # SEO
            'meta_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Leave blank to use store name',
                'maxlength': 60,
            }),
            'meta_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief description of your store (160 characters max)',
                'maxlength': 160,
            }),
            'meta_keywords': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'keyword1, keyword2, keyword3',
                'maxlength': 255,
            }),

            # Custom CSS
            'custom_css': forms.Textarea(attrs={
                'class': 'form-control font-monospace',
                'rows': 10,
                'placeholder': '/* Add your custom CSS here */\n.store-page {\n  /* Your styles */\n}',
                'spellcheck': 'false',
            }),
        }

        labels = {
            'theme_preset': 'Theme Preset',
            'primary_color': 'Primary Brand Color',
            'secondary_color': 'Secondary Color',
            'accent_color': 'Accent Color',
            'background_color': 'Background Color',
            'text_color': 'Text Color',
            'font_heading': 'Heading Font',
            'font_body': 'Body Font',
            'product_layout': 'Product Display Layout',
            'products_per_row': 'Products Per Row',
            'show_product_ratings': 'Show Product Ratings',
            'show_product_badges': 'Show Product Badges',
            'show_quick_view': 'Enable Quick View',
            'show_store_description': 'Show Store Description',
            'show_store_stats': 'Show Store Statistics',
            'show_social_links': 'Show Social Media Links',
            'show_operating_hours': 'Show Operating Hours',
            'show_map_location': 'Show Map Location',
            'header_message': 'Announcement Message',
            'show_header_message': 'Display Announcement',
            'banner_overlay_opacity': 'Banner Overlay Darkness',
            'banner_height': 'Banner Height',
            'cta_button_text': 'Call-to-Action Button Text',
            'cta_button_style': 'Button Style',
            'product_card_style': 'Product Card Style',
            'product_image_shape': 'Product Image Shape',
            'enable_animations': 'Enable Animations',
            'enable_hover_effects': 'Enable Hover Effects',
            'enable_parallax_banner': 'Parallax Banner Effect',
            'enable_featured_products': 'Featured Products Section',
            'enable_new_arrivals': 'New Arrivals Section',
            'enable_best_sellers': 'Best Sellers Section',
            'enable_testimonials': 'Testimonials Section',
            'show_secure_checkout_badge': 'Secure Checkout Badge',
            'show_free_shipping_badge': 'Free Shipping Badge',
            'show_money_back_guarantee': 'Money Back Guarantee',
            'show_customer_support_badge': '24/7 Support Badge',
            'mobile_menu_style': 'Mobile Menu Style',
            'meta_title': 'SEO Title',
            'meta_description': 'SEO Description',
            'meta_keywords': 'SEO Keywords',
            'enable_lazy_loading': 'Lazy Load Images',
            'enable_image_optimization': 'Optimize Images',
            'custom_css': 'Custom CSS Code',
        }

        help_texts = {
            'theme_preset': 'Start with a pre-designed theme, then customize it to your liking',
            'primary_color': 'Main color used throughout your store',
            'custom_css': 'Advanced: Add custom CSS to override default styles',
            'meta_description': 'This appears in search engine results',
            'header_message': 'Display a promotional message at the top of your store',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add custom attributes for better UX
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
                field.widget.attrs['role'] = 'switch'

            # Add data attributes for live preview
            if field_name in ['primary_color', 'secondary_color', 'accent_color']:
                field.widget.attrs['data-preview'] = 'color'
            elif field_name in ['font_heading', 'font_body']:
                field.widget.attrs['data-preview'] = 'font'
            elif field_name == 'theme_preset':
                field.widget.attrs['data-preview'] = 'theme'

    def clean_custom_css(self):
        """Validate custom CSS for security"""
        css = self.cleaned_data.get('custom_css', '')
        if css:
            # Basic validation - check for potentially dangerous content
            dangerous_patterns = ['javascript:', 'expression(', 'import', '@import', 'behavior:']
            css_lower = css.lower()
            for pattern in dangerous_patterns:
                if pattern in css_lower:
                    raise forms.ValidationError(
                        f'Custom CSS contains potentially dangerous code: {pattern}'
                    )
        return css

    def clean(self):
        cleaned_data = super().clean()

        # Ensure contrast between text and background colors
        text_color = cleaned_data.get('text_color')
        bg_color = cleaned_data.get('background_color')

        if text_color and bg_color:
            # Simple check - ensure they're not too similar
            if text_color.lower() == bg_color.lower():
                self.add_error('text_color', 'Text color must be different from background color')

        return cleaned_data


class StoreThemePresetForm(forms.Form):
    """
    Quick form for applying theme presets
    """
    PRESET_THEMES = [
        ('modern', 'Modern & Clean', {
            'primary_color': '#2563eb',
            'secondary_color': '#64748b',
            'accent_color': '#f59e0b',
            'background_color': '#ffffff',
            'text_color': '#1e293b',
            'font_heading': 'poppins',
            'font_body': 'inter',
        }),
        ('elegant', 'Elegant & Luxury', {
            'primary_color': '#1f2937',
            'secondary_color': '#d4af37',
            'accent_color': '#b8860b',
            'background_color': '#faf9f6',
            'text_color': '#1f2937',
            'font_heading': 'playfair',
            'font_body': 'lato',
        }),
        ('vibrant', 'Vibrant & Bold', {
            'primary_color': '#ec4899',
            'secondary_color': '#8b5cf6',
            'accent_color': '#f59e0b',
            'background_color': '#ffffff',
            'text_color': '#111827',
            'font_heading': 'montserrat',
            'font_body': 'roboto',
        }),
        ('minimal', 'Minimal & Simple', {
            'primary_color': '#000000',
            'secondary_color': '#6b7280',
            'accent_color': '#ffffff',
            'background_color': '#ffffff',
            'text_color': '#000000',
            'font_heading': 'inter',
            'font_body': 'inter',
        }),
        ('dark', 'Dark Mode', {
            'primary_color': '#3b82f6',
            'secondary_color': '#6366f1',
            'accent_color': '#10b981',
            'background_color': '#111827',
            'text_color': '#f9fafb',
            'font_heading': 'inter',
            'font_body': 'roboto',
        }),
    ]

    theme = forms.ChoiceField(
        choices=[(theme[0], theme[1]) for theme in PRESET_THEMES],
        widget=forms.RadioSelect,
        label='Choose a Theme Preset'
    )

    def get_theme_data(self):
        """Return the theme data for the selected preset"""
        theme_choice = self.cleaned_data.get('theme')
        for preset in self.PRESET_THEMES:
            if preset[0] == theme_choice:
                return preset[2]
        return {}
