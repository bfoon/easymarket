// Search functionality - works with both header and mobile search
function filterProducts() {
    // Get search term from header search or mobile search
    const headerSearch = document.querySelector('.navbar .search-bar');
    const mobileSearch = document.getElementById('mobileSearchInput');
    const searchTerm = (headerSearch?.value || mobileSearch?.value || '').toLowerCase();

    const products = document.querySelectorAll('.product-item');
    let visibleCount = 0;

    products.forEach(product => {
        const productName = product.dataset.name;
        const productDescription = product.querySelector('.card-text').textContent.toLowerCase();

        if (productName.includes(searchTerm) || productDescription.includes(searchTerm)) {
            product.style.display = 'block';
            visibleCount++;
            // Highlight search term
            const titleElement = product.querySelector('.card-title');
            titleElement.innerHTML = highlightText(titleElement.textContent, searchTerm);
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

// Connect header search to filter function
document.addEventListener('DOMContentLoaded', function() {
    // Connect header search
    const headerSearch = document.querySelector('.navbar .search-bar');
    if (headerSearch) {
        headerSearch.addEventListener('input', function() {
            if (this.value.length >= 2 || this.value.length === 0) {
                filterProducts();
            }
        });

        // Connect header search button
        const headerSearchBtn = document.querySelector('.navbar .btn-primary');
        if (headerSearchBtn) {
            headerSearchBtn.addEventListener('click', filterProducts);
        }
    }

    // Connect mobile search
    const mobileSearch = document.getElementById('mobileSearchInput');
    if (mobileSearch) {
        mobileSearch.addEventListener('input', function() {
            if (this.value.length >= 2 || this.value.length === 0) {
                filterProducts();
            }
        });
    }

    // Enable Bootstrap tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[title]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
});

// Highlight search text
function highlightText(text, searchTerm) {
    if (!searchTerm) return text;
    const regex = new RegExp(`(${searchTerm})`, 'gi');
    return text.replace(regex, '<span class="highlight">$1</span>');
}

// Sort functionality
function sortProducts(sortType) {
    const container = document.getElementById('productsContainer');
    const products = Array.from(container.querySelectorAll('.product-item'));

    products.sort((a, b) => {
        switch(sortType) {
            case 'price-low':
                return parseFloat(a.dataset.price) - parseFloat(b.dataset.price);
            case 'price-high':
                return parseFloat(b.dataset.price) - parseFloat(a.dataset.price);
            case 'name':
                return a.dataset.name.localeCompare(b.dataset.name);
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

    if (mode === 'list') {
        container.classList.add('list-view');
        listBtn.classList.add('active');
        gridBtn.classList.remove('active');
    } else {
        container.classList.remove('list-view');
        gridBtn.classList.add('active');
        listBtn.classList.remove('active');
    }
}

// Quick view modal
function quickView(name, description, price, image) {
    document.getElementById('modalProductName').textContent = name;
    document.getElementById('modalProductDescription').textContent = description;
    document.getElementById('modalProductPrice').textContent = '$' + price;
    document.getElementById('modalProductImage').src = image;

    const modal = new bootstrap.Modal(document.getElementById('quickViewModal'));
    modal.show();
}

// Add to cart functionality with real AJAX call
function addToCart(productId, button) {
    if (!button) return;

    // Add loading state
    button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Adding...';
    button.disabled = true;

    fetch(`/add-to-cart/${productId}/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCSRFToken(),
            'Accept': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
    if (data.success) {
        button.innerHTML = '<i class="fas fa-check me-1"></i> Added!';
        button.classList.remove('btn-outline-primary');
        button.classList.add('btn-success');

        showToast(data.product_name);

        // ✅ Update cart count dynamically
        updateCartCount(data.cart_count);

        setTimeout(() => {
            button.innerHTML = '<i class="fas fa-cart-plus me-1"></i> Add to Cart';
            button.classList.remove('btn-success');
            button.classList.add('btn-outline-primary');
            button.disabled = false;
        }, 2000);
    } else {
        showToast('Failed to add to cart.', 'danger');
        resetButton(button);
    }
})
    .catch(() => {
        showToast('Error adding to cart.', 'danger');
        resetButton(button);
    });
}


function resetButton(button) {
    button.innerHTML = '<i class="fas fa-cart-plus me-1"></i> Add to Cart';
    button.disabled = false;
}

function showToast(message, type = 'success') {
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
    `;

    const bgColor = type === 'success' ? '#067d62' : '#c0392b';
    const iconClass = type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle';
    const headerText = type === 'success' ? 'Added to Cart' : 'Alert';

    toast.innerHTML = `
        <div class="toast-header d-flex align-items-center justify-content-between" style="background-color: ${bgColor}; color: white; padding: 0.75rem 1rem;">
            <div class="d-flex align-items-center">
                <i class="fas ${iconClass} me-2"></i>
                <strong>${headerText}</strong>
            </div>
            <button type="button" class="btn-close btn-close-white" style="margin-left: auto;"></button>
        </div>
        <div class="toast-body d-flex align-items-center" style="background-color: white; color: #232f3e; font-size: 0.95rem; padding: 1rem;">
            <i class="fas fa-shopping-cart me-2 text-success"></i>
            <span><strong>${message}</strong> was successfully added!</span>
        </div>
    `;

    document.body.appendChild(toast);

    // Dismiss button functionality
    toast.querySelector('.btn-close').addEventListener('click', () => {
        toast.remove();
    });

    // Auto-remove after 3 seconds
    setTimeout(() => {
        if (toast.parentElement) {
            toast.remove();
        }
    }, 3000);
}

function getCSRFToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
}

function updateCartCount(count) {
    const countBadge = document.getElementById('cartCountBadge');
    if (countBadge) {
        countBadge.textContent = count;
        countBadge.style.display = count > 0 ? 'inline-block' : 'none';
    }
}

// Add to wishlist
function addToWishlist(productId) {
    const heartIcon = event.target.querySelector('i') || event.target;
    heartIcon.classList.toggle('far');
    heartIcon.classList.toggle('fas');
    heartIcon.classList.toggle('text-danger');

    showToast('Added to wishlist!');
}


// Load more products (for pagination)
function loadMoreProducts() {
    const loadBtn = document.getElementById('loadMoreBtn');
    loadBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Loading...';
    loadBtn.disabled = true;

    // Simulate loading
    setTimeout(() => {
        loadBtn.innerHTML = 'Load More Products';
        loadBtn.disabled = false;
        // Here you would load more products via AJAX
    }, 2000);
}

// Real-time search
document.getElementById('searchInput').addEventListener('input', function() {
    const searchTerm = this.value.toLowerCase();
    if (searchTerm.length >= 2 || searchTerm.length === 0) {
        filterProducts();
    }
});

// Initialize tooltips
document.addEventListener('DOMContentLoaded', function() {
    // Enable Bootstrap tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[title]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
});