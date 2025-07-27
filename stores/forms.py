from django import forms
from marketplace.models import Product, ProductImage, Category, ProductVariant, ProductFeatureOption
from django.core.exceptions import ValidationError
from .models import Store, StoreHours, StoreShippingZone, StoreReturnSettings
import re


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