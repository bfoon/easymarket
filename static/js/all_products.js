document.addEventListener('DOMContentLoaded', function () {
    // Product scroll functionality
    const sections = document.querySelectorAll('.products-container');

    sections.forEach(section => {
        const parent = section.closest('.position-relative');
        const leftBtn = parent.querySelector('.scroll-left');
        const rightBtn = parent.querySelector('.scroll-right');

        // Scroll amount based on card width + gap
        const scrollAmount = 200;

        leftBtn.addEventListener('click', () => {
            section.scrollBy({ left: -scrollAmount, behavior: 'smooth' });
        });

        rightBtn.addEventListener('click', () => {
            section.scrollBy({ left: scrollAmount, behavior: 'smooth' });
        });

        // Hide/show scroll buttons based on scroll position
        function updateScrollButtons() {
            const isAtStart = section.scrollLeft <= 0;
            const isAtEnd = section.scrollLeft >= section.scrollWidth - section.clientWidth;

            leftBtn.style.opacity = isAtStart ? '0.5' : '1';
            rightBtn.style.opacity = isAtEnd ? '0.5' : '1';
            leftBtn.disabled = isAtStart;
            rightBtn.disabled = isAtEnd;
        }

        section.addEventListener('scroll', updateScrollButtons);
        updateScrollButtons(); // Initial state
    });

    // Product card hover effects
    const productCards = document.querySelectorAll('.product-card');
    productCards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-5px)';
        });

        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0)';
        });
    });

    // Hide scrollbar in products container
    const style = document.createElement('style');
    style.textContent = `
        .products-container::-webkit-scrollbar {
            display: none;
        }
    `;
    document.head.appendChild(style);
});

// Enhanced add to cart function with feedback
function addToCart(productId) {
    // Show loading state
    const button = event.target.closest('button');
    const originalText = button.innerHTML;
    button.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Adding...';
    button.disabled = true;

    // Simulate API call (replace with your actual implementation)
    fetch(`/marketplace/add-to-cart/${productId}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({
            product_id: productId,
            quantity: 1
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Success feedback
            button.innerHTML = '<i class="fas fa-check me-2"></i>Added!';
            button.classList.remove('btn-primary');
            button.classList.add('btn-success');

            // Show toast notification (if you have a toast system)
            showToast('Product added to cart successfully!', 'success');

            // Reset button after 2 seconds
            setTimeout(() => {
                button.innerHTML = originalText;
                button.classList.remove('btn-success');
                button.classList.add('btn-primary');
                button.disabled = false;
            }, 2000);
        } else {
            throw new Error(data.message || 'Failed to add to cart');
        }
    })
    .catch(error => {
        // Error feedback
        button.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i>Error';
        button.classList.remove('btn-primary');
        button.classList.add('btn-danger');

        showToast('Failed to add product to cart', 'error');

        // Reset button after 2 seconds
        setTimeout(() => {
            button.innerHTML = originalText;
            button.classList.remove('btn-danger');
            button.classList.add('btn-primary');
            button.disabled = false;
        }, 2000);
    });
}

// Enhanced add to wishlist function
function addToWishlist(productId) {
    const button = event.target.closest('button');
    const icon = button.querySelector('i');

    // Toggle wishlist state
    if (icon.classList.contains('far')) {
        icon.classList.remove('far');
        icon.classList.add('fas');
        button.classList.remove('btn-outline-secondary');
        button.classList.add('btn-outline-danger');
        showToast('Added to wishlist!', 'success');
    } else {
        icon.classList.remove('fas');
        icon.classList.add('far');
        button.classList.remove('btn-outline-danger');
        button.classList.add('btn-outline-secondary');
        showToast('Removed from wishlist', 'info');
    }

    // Here you would make an actual API call to update the wishlist
    // fetch(`/marketplace/toggle-wishlist/${productId}/`, {...})
}

// Simple toast notification function
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `alert alert-${type === 'error' ? 'danger' : type} position-fixed`;
    toast.style.cssText = 'top: 20px; right: 20px; z-index: 1060; min-width: 300px;';
    toast.innerHTML = `
        <div class="d-flex align-items-center">
            <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'} me-2"></i>
            ${message}
            <button type="button" class="btn-close ms-auto" onclick="this.parentElement.parentElement.remove()"></button>
        </div>
    `;

    document.body.appendChild(toast);

    // Auto remove after 3 seconds
    setTimeout(() => {
        if (toast.parentElement) {
            toast.remove();
        }
    }, 3000);
}