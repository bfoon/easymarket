from django import forms
from marketplace.models import Product, ProductImage, Category, ProductVariant, ProductFeatureOption

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name', 'category', 'price', 'original_price', 'description',
            'specifications', 'image', 'video', 'is_featured', 'is_trending',
            'has_30_day_return', 'free_shipping'
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
    class Meta:
        model = ProductImage
        fields = ['image']
        widgets = {
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure the image field is not required (to allow blank extra forms)
        self.fields['image'].required = False


class ProductVariantForm(forms.ModelForm):
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
            'has_30_day_return', 'free_shipping'
        ]
        widgets = {
            # keep your existing widgets here...
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
