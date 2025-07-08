function toggleAddressInput() {
    const addressSection = document.getElementById('address-input-section');
    const deliveryAddress = document.getElementById('delivery-address');
    const currentAddress = deliveryAddress.textContent.trim();

    if (!currentAddress.includes('Please add your delivery address')) {
        document.getElementById('new-address').value = currentAddress;
    }

    addressSection.classList.remove('d-none');
    deliveryAddress.parentElement.classList.add('d-none');
}

function cancelAddressEdit() {
    const addressSection = document.getElementById('address-input-section');
    const deliveryAddress = document.getElementById('delivery-address');

    addressSection.classList.add('d-none');
    deliveryAddress.parentElement.classList.remove('d-none');
    document.getElementById('new-address').value = '';
}

function updateAddress() {
    const newAddress = document.getElementById('new-address').value.trim();
    if (!newAddress) {
        alert('Please enter a valid address');
        return;
    }

    // Update the display
    document.getElementById('delivery-address').textContent = newAddress;

    // Here you would typically make an AJAX call to update the user's address
    // Example:
    // fetch('/update-address/', {
    //     method: 'POST',
    //     headers: {
    //         'Content-Type': 'application/json',
    //         'X-CSRFToken': getCookie('csrftoken')
    //     },
    //     body: JSON.stringify({ address: newAddress })
    // });

    cancelAddressEdit();
    alert('Address updated successfully!');
}

function calculateDeliveryDate() {
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);

    const options = {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    };

    const deliveryDateElement = document.getElementById('delivery-date');
    if (deliveryDateElement) {
        deliveryDateElement.textContent = tomorrow.toLocaleDateString('en-US', options);
    }
}

// Calculate delivery date when page loads
document.addEventListener('DOMContentLoaded', function() {
    calculateDeliveryDate();
});

function changeMainImage(thumbnail, imageUrl) {
    document.getElementById('mainProductImage').src = imageUrl;

    // Update active thumbnail
    document.querySelectorAll('.thumbnail-item').forEach(item => {
        item.classList.remove('active');
    });
    thumbnail.classList.add('active');
}

// Quantity controls
function changeQuantity(change) {
    const quantityInput = document.getElementById('quantity');
    if (quantityInput) {
        const currentValue = parseInt(quantityInput.value);
        const newValue = currentValue + change;
        const min = parseInt(quantityInput.min);
        const max = parseInt(quantityInput.max);

        if (newValue >= min && newValue <= max) {
            quantityInput.value = newValue;
        }
    }
}

// Image zoom effect
document.getElementById('mainProductImage').addEventListener('mousemove', function(e) {
    const rect = this.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const xPercent = (x / rect.width) * 100;
    const yPercent = (y / rect.height) * 100;

    this.style.transformOrigin = `${xPercent}% ${yPercent}%`;
    this.style.transform = 'scale(1.5)';
});

document.getElementById('mainProductImage').addEventListener('mouseleave', function() {
    this.style.transform = 'scale(1)';
});

function buyNow(productId) {
    const form = document.getElementById('buyNowForm');
    const productInput = document.getElementById('buyNowProduct');
    const quantityInput = document.getElementById('quantity');

    const quantity = parseInt(quantityInput.value);

    if (isNaN(quantity) || quantity < 1) {
        alert('Please select a valid quantity.');
        return;
    }

    productInput.value = productId;
    form.querySelector('input[name="quantity"]').value = quantity;
    form.submit();
}
// Wishlist functionality
function toggleWishlist(productId) {
    const button = event.target.closest('button');
    const icon = button.querySelector('i');

    // Toggle heart icon
    if (icon.classList.contains('far')) {
        icon.classList.remove('far');
        icon.classList.add('fas');
        icon.style.color = '#dc3545';
    } else {
        icon.classList.remove('fas');
        icon.classList.add('far');
        icon.style.color = '';
    }

    // Here you would make an AJAX call to add/remove from wishlist
    console.log('Toggle wishlist for product:', productId);
}