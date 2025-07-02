// Enhanced scroll functionality for category carousels
document.addEventListener('DOMContentLoaded', function() {
    // Handle scroll buttons for all category carousels
    const scrollButtons = document.querySelectorAll('.scroll-left, .scroll-right');

    scrollButtons.forEach(button => {
        button.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            const container = document.getElementById(targetId);

            if (container) {
                const scrollAmount = 220; // Width of product card + gap
                const isScrollLeft = this.classList.contains('scroll-left');

                container.scrollBy({
                    left: isScrollLeft ? -scrollAmount : scrollAmount,
                    behavior: 'smooth'
                });
            }
        });
    });

    // Show/hide scroll buttons based on scroll position and content
    const productContainers = document.querySelectorAll('.products-container');

    productContainers.forEach(container => {
        const categoryBlock = container.closest('.category-block');
        if (!categoryBlock) return;

        const leftBtn = categoryBlock.querySelector('.scroll-left');
        const rightBtn = categoryBlock.querySelector('.scroll-right');

        // Initial check
        updateScrollButtons(container, leftBtn, rightBtn);

        // Update on scroll
        container.addEventListener('scroll', () => {
            updateScrollButtons(container, leftBtn, rightBtn);
        });

        // Update on resize
        window.addEventListener('resize', () => {
            updateScrollButtons(container, leftBtn, rightBtn);
        });
    });
});

function updateScrollButtons(container, leftBtn, rightBtn) {
    if (!container || !leftBtn || !rightBtn) return;

    const scrollLeft = container.scrollLeft;
    const scrollWidth = container.scrollWidth;
    const clientWidth = container.clientWidth;
    const isScrollable = scrollWidth > clientWidth;

    // Hide buttons if content doesn't scroll
    if (!isScrollable) {
        leftBtn.style.display = 'none';
        rightBtn.style.display = 'none';
        return;
    }

    leftBtn.style.display = 'block';
    rightBtn.style.display = 'block';

    // Update button states
    leftBtn.style.opacity = scrollLeft <= 5 ? '0.5' : '1';
    leftBtn.style.pointerEvents = scrollLeft <= 5 ? 'none' : 'auto';

    rightBtn.style.opacity = scrollLeft >= (scrollWidth - clientWidth - 5) ? '0.5' : '1';
    rightBtn.style.pointerEvents = scrollLeft >= (scrollWidth - clientWidth - 5) ? 'none' : 'auto';
}

// Add to Cart functionality
function addToCart(productId) {
    const button = event.target.closest('button');
    if (!button) return;

    const originalHTML = button.innerHTML;
    button.innerHTML = '<i class="fas fa-check me-1"></i> Added!';
    button.style.backgroundColor = 'var(--success-green)';
    button.style.borderColor = 'var(--success-green)';

    // Here you would make an AJAX call to add the product to cart
    console.log('Adding product to cart:', productId);

    setTimeout(() => {
        button.innerHTML = originalHTML;
        button.style.backgroundColor = '';
        button.style.borderColor = '';
    }, 2000);
}

// Add to Wishlist functionality
function addToWishlist(productId) {
    const button = event.target.closest('button');
    if (!button) return;

    const icon = button.querySelector('i');
    const originalHTML = button.innerHTML;

    button.innerHTML = '<i class="fas fa-heart me-1"></i> Added!';
    button.style.color = 'var(--warning-red)';
    button.style.borderColor = 'var(--warning-red)';

    // Here you would make an AJAX call to add the product to wishlist
    console.log('Adding product to wishlist:', productId);

    setTimeout(() => {
        button.innerHTML = originalHTML;
        button.style.color = '';
        button.style.borderColor = '';
    }, 2000);
}