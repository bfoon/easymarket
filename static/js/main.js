// static/js/main.js - General site-wide functionality

// ==============================================
// UTILITY FUNCTIONS
// ==============================================

// Get CSRF token for AJAX requests
function getCSRFToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
}

// Universal toast notification system
function showToast(message, type = 'success', title = null) {
    const toast = document.createElement('div');
    toast.className = `position-fixed shadow`;
    toast.style.cssText = `
        top: 20px;
        right: 20px;
        z-index: 1055;
        min-width: 320px;
        max-width: 400px;
        border-radius: 12px;
        overflow: hidden;
        animation: slideInRight 0.3s ease;
    `;

    const bgColor = type === 'success' ? '#067d62' : type === 'error' ? '#c0392b' : '#ffc107';
    const iconClass = type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle';
    const headerText = title || (type === 'success' ? 'Success' : type === 'error' ? 'Error' : 'Info');

    toast.innerHTML = `
        <div class="toast-header d-flex align-items-center justify-content-between" style="background-color: ${bgColor}; color: white; padding: 0.75rem 1rem;">
            <div class="d-flex align-items-center">
                <i class="fas ${iconClass} me-2"></i>
                <strong>${headerText}</strong>
            </div>
            <button type="button" class="btn-close btn-close-white" style="margin-left: auto;"></button>
        </div>
        <div class="toast-body" style="background-color: white; color: #232f3e; font-size: 0.95rem; padding: 1rem;">
            ${message}
        </div>
    `;

    document.body.appendChild(toast);

    // Dismiss button functionality
    toast.querySelector('.btn-close').addEventListener('click', () => {
        toast.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    });

    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (toast.parentElement) {
            toast.style.animation = 'slideOutRight 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}

// Update cart count in navigation
function updateCartCount(count) {
    const countBadge = document.getElementById('cartCountBadge');
    if (countBadge) {
        countBadge.textContent = count;
        countBadge.style.display = count > 0 ? 'inline-block' : 'none';

        // Add animation
        countBadge.style.transform = 'scale(1.3)';
        setTimeout(() => {
            countBadge.style.transform = 'scale(1)';
        }, 200);
    }
}

// ==============================================
// SEARCH FUNCTIONALITY
// ==============================================

// Universal search functionality - works with both header and mobile search
function filterProducts() {
    const headerSearch = document.querySelector('.navbar .search-bar');
    const mobileSearch = document.getElementById('mobileSearchInput');
    const searchInput = document.getElementById('searchInput'); // Fallback

    const searchTerm = (
        headerSearch?.value ||
        mobileSearch?.value ||
        searchInput?.value ||
        ''
    ).toLowerCase();

    const products = document.querySelectorAll('.product-item');
    let visibleCount = 0;

    products.forEach(product => {
        const productName = product.dataset.name?.toLowerCase() || '';
        const productDescription = product.querySelector('.card-text')?.textContent?.toLowerCase() || '';

        if (productName.includes(searchTerm) || productDescription.includes(searchTerm)) {
            product.style.display = 'block';
            visibleCount++;

            // Highlight search term
            const titleElement = product.querySelector('.card-title');
            if (titleElement) {
                titleElement.innerHTML = highlightText(titleElement.textContent, searchTerm);
            }
        } else {
            product.style.display = 'none';
        }
    });

    // Update product count
    const countElement = document.querySelector('.container h2 + p');
    if (countElement) {
        countElement.textContent = `${visibleCount} product${visibleCount !== 1 ? 's' : ''} found`;
    }
}

// Highlight search text
function highlightText(text, searchTerm) {
    if (!searchTerm) return text;
    const regex = new RegExp(`(${searchTerm})`, 'gi');
    return text.replace(regex, '<span class="highlight">$1</span>');
}

// ==============================================
// PRODUCT GRID FUNCTIONALITY
// ==============================================

// Sort functionality
function sortProducts(sortType) {
    const container = document.getElementById('productsContainer');
    if (!container) return;

    const products = Array.from(container.querySelectorAll('.product-item'));

    products.sort((a, b) => {
        switch(sortType) {
            case 'price-low':
                return parseFloat(a.dataset.price || 0) - parseFloat(b.dataset.price || 0);
            case 'price-high':
                return parseFloat(b.dataset.price || 0) - parseFloat(a.dataset.price || 0);
            case 'name':
                return (a.dataset.name || '').localeCompare(b.dataset.name || '');
            default:
                return 0;
        }
    });

    // Re-append sorted products
    products.forEach(product => container.appendChild(product));
}

// View mode toggle
function setViewMode(mode) {
    const container = document.getElementById('productsContainer');
    const gridBtn = document.getElementById('gridView');
    const listBtn = document.getElementById('listView');

    if (!container) return;

    if (mode === 'list') {
        container.classList.add('list-view');
        listBtn?.classList.add('active');
        gridBtn?.classList.remove('active');
    } else {
        container.classList.remove('list-view');
        gridBtn?.classList.add('active');
        listBtn?.classList.remove('active');
    }
}

// Quick view modal
function quickView(name, description, price, image) {
    const elements = {
        name: document.getElementById('modalProductName'),
        description: document.getElementById('modalProductDescription'),
        price: document.getElementById('modalProductPrice'),
        image: document.getElementById('modalProductImage')
    };

    if (elements.name) elements.name.textContent = name;
    if (elements.description) elements.description.textContent = description;
    if (elements.price) elements.price.textContent = 'D' + price;
    if (elements.image) elements.image.src = image;

    const modalElement = document.getElementById('quickViewModal');
    if (modalElement && typeof bootstrap !== 'undefined') {
        const modal = new bootstrap.Modal(modalElement);
        modal.show();
    }
}

// ==============================================
// CART FUNCTIONALITY
// ==============================================

// Add to cart functionality with AJAX
function addToCart(productId, button) {
    if (!button || !productId) return;

    const originalContent = button.innerHTML;

    // Add loading state
    button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Adding...';
    button.disabled = true;

    fetch(`/add-to-cart/${productId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCSRFToken(),
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            button.innerHTML = '<i class="fas fa-check me-1"></i> Added!';
            button.classList.remove('btn-outline-primary');
            button.classList.add('btn-success');

            showToast(`${data.product_name} was successfully added!`, 'success', 'Added to Cart');

            // Update cart count dynamically
            updateCartCount(data.cart_count);

            setTimeout(() => {
                button.innerHTML = originalContent;
                button.classList.remove('btn-success');
                button.classList.add('btn-outline-primary');
                button.disabled = false;
            }, 2000);
        } else {
            showToast(data.error || 'Failed to add to cart.', 'error');
            resetButton(button, originalContent);
        }
    })
    .catch(error => {
        console.error('Add to cart error:', error);
        showToast('Error adding to cart.', 'error');
        resetButton(button, originalContent);
    });
}

// Reset button to original state
function resetButton(button, originalContent) {
    if (button) {
        button.innerHTML = originalContent || '<i class="fas fa-cart-plus me-1"></i> Add to Cart';
        button.disabled = false;
        button.classList.remove('btn-success');
        button.classList.add('btn-outline-primary');
    }
}

// ==============================================
// WISHLIST FUNCTIONALITY
// ==============================================

// Universal wishlist toggle
function addToWishlist(productId, button) {
    const heartIcon = button?.querySelector('i') || button;
    if (!heartIcon) return;

    const originalClasses = heartIcon.className;

    fetch(`/wishlist/toggle/${productId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCSRFToken(),
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (data.status === 'added') {
                heartIcon.classList.remove('far');
                heartIcon.classList.add('fas', 'text-danger');
                showToast('Added to wishlist!', 'success');
            } else {
                heartIcon.classList.remove('fas', 'text-danger');
                heartIcon.classList.add('far');
                showToast('Removed from wishlist!', 'success');
            }
        } else {
            showToast(data.error || "Something went wrong.", 'error');
        }
    })
    .catch(error => {
        console.error('Wishlist toggle failed:', error);
        heartIcon.className = originalClasses; // Restore original state
        showToast("An error occurred while updating your wishlist.", 'error');
    });
}

// ==============================================
// PAGINATION
// ==============================================

// Load more products (for pagination)
function loadMoreProducts() {
    const loadBtn = document.getElementById('loadMoreBtn');
    if (!loadBtn) return;

    const originalContent = loadBtn.innerHTML;
    loadBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Loading...';
    loadBtn.disabled = true;

    // This would typically be an AJAX call to load more products
    setTimeout(() => {
        loadBtn.innerHTML = originalContent;
        loadBtn.disabled = false;
        // Here you would append new products to the container
    }, 2000);
}

// ==============================================
// SCROLL TO TOP
// ==============================================

// Scroll to top functionality
function initScrollToTop() {
    const scrollToTopBtn = document.getElementById('scrollToTopBtn');
    if (scrollToTopBtn) {
        scrollToTopBtn.addEventListener('click', function() {
            window.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        });

        // Show/hide scroll to top button
        window.addEventListener('scroll', function() {
            if (window.pageYOffset > 300) {
                scrollToTopBtn.style.display = 'block';
            } else {
                scrollToTopBtn.style.display = 'none';
            }
        });
    }
}

// ==============================================
// INITIALIZATION
// ==============================================

document.addEventListener('DOMContentLoaded', function() {
    // Initialize search functionality
    const searchElements = [
        document.querySelector('.navbar .search-bar'),
        document.getElementById('mobileSearchInput'),
        document.getElementById('searchInput')
    ];

    searchElements.forEach(element => {
        if (element) {
            element.addEventListener('input', function() {
                if (this.value.length >= 2 || this.value.length === 0) {
                    filterProducts();
                }
            });
        }
    });

    // Connect search buttons
    const searchButtons = document.querySelectorAll('.navbar .btn-primary, .mobile-search-btn');
    searchButtons.forEach(btn => {
        if (btn) {
            btn.addEventListener('click', filterProducts);
        }
    });

    // Initialize tooltips if Bootstrap is available
    if (typeof bootstrap !== 'undefined') {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[title]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // Initialize scroll to top
    initScrollToTop();

    // Add CSS for animations
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideInRight {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }

        @keyframes slideOutRight {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(100%); opacity: 0; }
        }

        .highlight {
            background-color: #fff3cd;
            color: #856404;
            padding: 0.1em 0.2em;
            border-radius: 0.2em;
        }

        .btn-loading {
            position: relative;
            pointer-events: none;
        }

        #scrollToTopBtn {
            display: none;
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 1000;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            cursor: pointer;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            transition: all 0.3s ease;
        }

        #scrollToTopBtn:hover {
            background: #0056b3;
            transform: translateY(-2px);
        }
    `;
    document.head.appendChild(style);
});

// Make functions globally available
window.filterProducts = filterProducts;
window.sortProducts = sortProducts;
window.setViewMode = setViewMode;
window.quickView = quickView;
window.addToCart = addToCart;
window.addToWishlist = addToWishlist;
window.loadMoreProducts = loadMoreProducts;
window.showToast = showToast;
window.getCSRFToken = getCSRFToken;
window.updateCartCount = updateCartCount;