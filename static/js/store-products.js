document.addEventListener('DOMContentLoaded', function() {
    initializeEnhancements();
});

function initializeEnhancements() {
    setupFilters();
    setupSearch();
    setupSorting();
    setupAccessibility();
    setupLazyLoading();
}

function setupFilters() {
    // Add event listeners to enhanced form controls
    document.querySelectorAll('.enhanced-form-check input').forEach(input => {
        input.addEventListener('change', debounce(applyFilters, 300));
    });
}

function setupSearch() {
    const searchInput = document.getElementById('productSearch');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(function() {
            filterProducts();
        }, 300));
    }
}

function setupSorting() {
    const sortSelect = document.getElementById('sortProducts');
    if (sortSelect) {
        sortSelect.addEventListener('change', function() {
            showLoading();
            setTimeout(() => {
                applySort(this.value);
                hideLoading();
            }, 300);
        });
    }
}

function setupAccessibility() {
    // Add keyboard navigation for view toggles
    document.querySelectorAll('.enhanced-view-btn').forEach(btn => {
        btn.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.click();
            }
        });
    });
}

function setupLazyLoading() {
    // Enhanced lazy loading with intersection observer
    const images = document.querySelectorAll('img[loading="lazy"]');

    if ('IntersectionObserver' in window) {
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    img.classList.add('loaded');
                    observer.unobserve(img);
                }
            });
        });

        images.forEach(img => imageObserver.observe(img));
    }
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function applyFilters() {
    const filters = {
        categories: [],
        availability: [],
        features: [],
        rating: null
    };

    // Collect category filters
    if (!document.getElementById('all-categories')?.checked) {
        ['electronics', 'fashion', 'home'].forEach(cat => {
            const checkbox = document.getElementById(cat);
            if (checkbox?.checked) {
                filters.categories.push(cat);
            }
        });
    }

    // Collect availability filters
    ['in-stock', 'out-of-stock'].forEach(availability => {
        const checkbox = document.getElementById(availability);
        if (checkbox?.checked) {
            filters.availability.push(availability);
        }
    });

    // Collect feature filters
    ['free-shipping', 'on-sale', 'featured'].forEach(feature => {
        const checkbox = document.getElementById(feature);
        if (checkbox?.checked) {
            filters.features.push(feature);
        }
    });

    // Get rating filter
    const selectedRating = document.querySelector('input[name="rating"]:checked');
    if (selectedRating && selectedRating.id !== 'rating-all') {
        filters.rating = selectedRating.id.replace('rating-', '');
    }

    filterProducts(filters);
}

function filterProducts(filters = {}) {
    const searchTerm = document.getElementById('productSearch')?.value.toLowerCase() || '';
    const cards = document.querySelectorAll('.product-card');
    let visibleCount = 0;

    showLoading();

    setTimeout(() => {
        cards.forEach(card => {
            let show = true;

            // Search filter
            if (searchTerm) {
                const productName = card.dataset.name || '';
                if (!productName.includes(searchTerm)) {
                    show = false;
                }
            }

            // Category filter
            if (filters.categories && filters.categories.length > 0) {
                const productCategory = card.dataset.category || '';
                if (!filters.categories.some(cat => productCategory.includes(cat))) {
                    show = false;
                }
            }

            // Stock filter
            if (filters.availability && filters.availability.length > 0) {
                const productStock = card.dataset.stock || '';
                if (!filters.availability.includes(productStock)) {
                    show = false;
                }
            }

            // Rating filter
            if (filters.rating) {
                const productRating = parseFloat(card.dataset.rating || 0);
                const requiredRating = parseInt(filters.rating);
                if (productRating < requiredRating) {
                    show = false;
                }
            }

            if (show) {
                card.style.display = 'block';
                visibleCount++;
            } else {
                card.style.display = 'none';
            }
        });

        updateResultsCount(visibleCount);
        hideLoading();

        if (visibleCount === 0) {
            showNoResults();
        } else {
            hideNoResults();
        }
    }, 300);
}

function applyPriceFilter() {
    const minPrice = parseFloat(document.getElementById('minPrice')?.value) || 0;
    const maxPrice = parseFloat(document.getElementById('maxPrice')?.value) || Infinity;

    showLoading();

    setTimeout(() => {
        document.querySelectorAll('.product-card').forEach(card => {
            const price = parseFloat(card.dataset.price) || 0;
            const show = price >= minPrice && price <= maxPrice;
            card.style.display = show ? 'block' : 'none';
        });

        hideLoading();
        showEnhancedToast('Price filter applied', 'success');
    }, 300);
}

function applySort(sortBy) {
    const container = document.getElementById('productsContainer');
    const cards = Array.from(container.children);

    cards.sort((a, b) => {
        switch(sortBy) {
            case 'price-low':
                return parseFloat(a.dataset.price || 0) - parseFloat(b.dataset.price || 0);
            case 'price-high':
                return parseFloat(b.dataset.price || 0) - parseFloat(a.dataset.price || 0);
            case 'alphabetical':
                return (a.dataset.name || '').localeCompare(b.dataset.name || '');
            case 'rating':
                return parseFloat(b.dataset.rating || 0) - parseFloat(a.dataset.rating || 0);
            default:
                return 0;
        }
    });

    cards.forEach(card => container.appendChild(card));
    showEnhancedToast('Products sorted successfully', 'success');
}

function clearFilters() {
    // Reset all form inputs
    document.querySelectorAll('.enhanced-form-check input[type="checkbox"]').forEach(checkbox => {
        checkbox.checked = checkbox.id === 'all-categories' || checkbox.id === 'in-stock';
    });

    const ratingAll = document.getElementById('rating-all');
    if (ratingAll) ratingAll.checked = true;

    ['minPrice', 'maxPrice', 'productSearch'].forEach(id => {
        const element = document.getElementById(id);
        if (element) element.value = '';
    });

    // Show all products
    document.querySelectorAll('.product-card').forEach(card => {
        card.style.display = 'block';
    });

    updateResultsCount(document.querySelectorAll('.product-card').length);
    showEnhancedToast('All filters cleared', 'success');
}

function setViewMode(mode) {
    const container = document.getElementById('productsContainer');
    const buttons = document.querySelectorAll('.enhanced-view-btn');

    buttons.forEach(btn => btn.classList.remove('active'));
    event.target.closest('button').classList.add('active');

    if (mode === 'list') {
        container.classList.add('enhanced-list-view');
        container.querySelectorAll('.product-card').forEach(card => {
            card.className = 'col-12 mb-3 product-card';
        });
    } else {
        container.classList.remove('enhanced-list-view');
        container.querySelectorAll('.product-card').forEach(card => {
            card.className = 'col-lg-4 col-md-6 mb-4 product-card';
        });
    }

    showEnhancedToast(`View changed to ${mode} mode`, 'success');
}

function toggleWishlist(productId) {
    showEnhancedToast('Added to wishlist', 'success');
}

function addToCompare(productId) {
    showEnhancedToast('Added to comparison list', 'success');
}

function showLoading() {
    const indicator = document.getElementById('loadingIndicator');
    if (indicator) {
        indicator.style.display = 'flex';
    }
}

function hideLoading() {
    const indicator = document.getElementById('loadingIndicator');
    if (indicator) {
        indicator.style.display = 'none';
    }
}

function showEnhancedToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');

    const icons = {
        success: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle',
        warning: 'fas fa-exclamation-triangle'
    };

    toast.className = `enhanced-toast ${type}`;
    toast.innerHTML = `
        <i class="${icons[type]}"></i>
        <span>${message}</span>
        <button type="button" class="btn-close btn-sm ms-auto" onclick="this.parentElement.remove()" aria-label="Close notification"></button>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        if (toast.parentElement) {
            toast.remove();
        }
    }, 5000);
}

function updateResultsCount(count) {
    const elements = ['resultsStart', 'resultsEnd', 'resultsTotal'];
    elements.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = count;
        }
    });
}

function showNoResults() {
    // Implementation can be added as needed
}

function hideNoResults() {
    // Implementation can be added as needed
}

function updateCartCounter() {
    // Update cart counter in navigation
    const cartCounter = document.querySelector('.cart-counter');
    if (cartCounter) {
        cartCounter.textContent = parseInt(cartCounter.textContent || 0) + 1;
    }
}