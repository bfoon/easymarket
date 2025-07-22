from django import forms
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from marketplace.models import Product
from .models import Auction, Bid, AuctionCategory, AuctionQuestion

class AuctionForm(forms.ModelForm):
    end_date = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text="Auction end date and time"
    )

    class Meta:
        model = Auction
        fields = [
            'title', 'description', 'auction_type', 'category',
            'starting_bid', 'reserve_price', 'buy_now_price', 'increment_amount',
            'end_date', 'image', 'shipping_required', 'shipping_cost',
            'international_shipping', 'auto_extend', 'marketplace_product'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5, 'class': 'form-control'}),
            'starting_bid': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'class': 'form-control'}),
            'reserve_price': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'class': 'form-control'}),
            'buy_now_price': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'class': 'form-control'}),
            'increment_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'class': 'form-control'}),
            'shipping_cost': forms.NumberInput(attrs={'step': '0.01', 'min': '0.00', 'class': 'form-control'}),
            'marketplace_product': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        # Filter marketplace products to user's store products
        if user and hasattr(user, 'owned_stores'):
            user_stores = user.owned_stores.filter(status='active')
            if user_stores.exists():

                self.fields['marketplace_product'].queryset = Product.objects.filter(
                    store__in=user_stores,
                    is_active=True
                )
            else:
                self.fields['marketplace_product'].queryset = Product.objects.none()

        for field in self.fields.values():
            if 'class' not in field.widget.attrs:
                field.widget.attrs.update({'class': 'form-control'})

        # Set minimum end date to 1 hour from now
        min_end_date = timezone.now() + timedelta(hours=1)
        self.fields['end_date'].widget.attrs['min'] = min_end_date.strftime('%Y-%m-%dT%H:%M')

    def clean_end_date(self):
        end_date = self.cleaned_data['end_date']
        if end_date <= timezone.now() + timedelta(hours=1):
            raise forms.ValidationError("Auction must end at least 1 hour from now.")
        return end_date

    def clean(self):
        cleaned_data = super().clean()
        starting_bid = cleaned_data.get('starting_bid')
        reserve_price = cleaned_data.get('reserve_price')
        buy_now_price = cleaned_data.get('buy_now_price')

        if reserve_price and starting_bid and reserve_price < starting_bid:
            raise forms.ValidationError("Reserve price cannot be less than starting bid.")

        if buy_now_price and starting_bid and buy_now_price <= starting_bid:
            raise forms.ValidationError("Buy now price must be greater than starting bid.")

        return cleaned_data


class BidForm(forms.ModelForm):
    max_auto_bid = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'step': '0.01',
            'class': 'form-control',
            'placeholder': 'Optional: Maximum auto-bid amount'
        }),
        help_text="System will automatically bid up to this amount for you"
    )

    class Meta:
        model = Bid
        fields = ['amount', 'max_auto_bid']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'step': '0.01',
                'min': '0.01',
                'class': 'form-control',
                'placeholder': 'Enter your bid amount'
            })
        }

    def __init__(self, auction=None, user=None, *args, **kwargs):
        self.auction = auction
        self.user = user
        super().__init__(*args, **kwargs)

        if auction:
            min_bid = auction.minimum_bid
            self.fields['amount'].widget.attrs['min'] = str(min_bid)
            self.fields['amount'].help_text = f"Minimum bid: ${min_bid}"

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if self.auction:
            min_bid = self.auction.minimum_bid
            if amount < min_bid:
                raise forms.ValidationError(f"Bid must be at least ${min_bid}")
        return amount

    def clean_max_auto_bid(self):
        max_auto_bid = self.cleaned_data.get('max_auto_bid')
        amount = self.cleaned_data.get('amount')

        if max_auto_bid and amount and max_auto_bid < amount:
            raise forms.ValidationError("Maximum auto-bid cannot be less than your current bid.")

        return max_auto_bid


class SearchForm(forms.Form):
    query = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search auctions...'
        })
    )
    category = forms.ModelChoiceField(
        queryset=AuctionCategory.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    auction_type = forms.ChoiceField(
        choices=[('', 'All Types')] + Auction.AUCTION_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    min_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Min price',
            'step': '0.01'
        })
    )
    max_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max price',
            'step': '0.01'
        })
    )
    ending_soon = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Ending within 24 hours"
    )
    reserve_met = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Reserve price met"
    )
    store = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="All Stores",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from stores.models import Store
        self.fields['store'].queryset = Store.objects.filter(status='active')


class QuestionForm(forms.ModelForm):
    class Meta:
        model = AuctionQuestion
        fields = ['question']
        widgets = {
            'question': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': 'Ask the seller a question about this item...'
            })
        }