// Reviews and Rating System
document.addEventListener('DOMContentLoaded', function() {
    const reviewForm = document.getElementById('review-form');
    const starInputs = document.querySelectorAll('.star-input');
    const ratingInput = document.getElementById('rating-input');
    const submitSpinner = document.getElementById('submit-spinner');
    const loadMoreBtn = document.getElementById('load-more-reviews');

    // Star rating functionality
    if (starInputs.length > 0) {
        starInputs.forEach((star, index) => {
            star.addEventListener('click', function() {
                const rating = this.dataset.rating;
                ratingInput.value = rating;

                // Update star display
                starInputs.forEach((s, i) => {
                    if (i < rating) {
                        s.classList.remove('far');
                        s.classList.add('fas');
                    } else {
                        s.classList.remove('fas');
                        s.classList.add('far');
                    }
                });
            });

            // Hover effect
            star.addEventListener('mouseenter', function() {
                const rating = this.dataset.rating;
                starInputs.forEach((s, i) => {
                    if (i < rating) {
                        s.classList.add('active');
                    } else {
                        s.classList.remove('active');
                    }
                });
            });
        });

        // Reset hover effect
        const starRating = document.querySelector('.star-rating');
        if (starRating) {
            starRating.addEventListener('mouseleave', function() {
                starInputs.forEach(s => s.classList.remove('active'));
            });
        }
    }

    // Submit review
    if (reviewForm) {
        reviewForm.addEventListener('submit', function(e) {
            e.preventDefault();

            const formData = new FormData(this);
            if (submitSpinner) {
                submitSpinner.classList.remove('d-none');
            }

            fetch('/reviews/submit/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                }
            })
            .then(response => response.json())
            .then(data => {
                if (submitSpinner) {
                    submitSpinner.classList.add('d-none');
                }

                if (data.success) {
                    // Update rating display
                    const ratingStars = document.getElementById('rating-stars');
                    const avgRating = document.getElementById('avg-rating');
                    const totalReviews = document.getElementById('total-reviews');

                    if (ratingStars) ratingStars.innerHTML = data.stars_html;
                    if (avgRating) avgRating.textContent = data.new_avg;
                    if (totalReviews) totalReviews.textContent = data.total_reviews;

                    // Show success message
                    showToast(data.message, 'success');

                    // Reset form
                    reviewForm.reset();
                    if (ratingInput) ratingInput.value = '';
                    starInputs.forEach(s => {
                        s.classList.remove('fas', 'active');
                        s.classList.add('far');
                    });

                    // Reload reviews
                    loadReviews(1);
                } else {
                    showToast(data.error, 'error');
                }
            })
            .catch(error => {
                if (submitSpinner) {
                    submitSpinner.classList.add('d-none');
                }
                showToast('An error occurred. Please try again.', 'error');
                console.error('Error:', error);
            });
        });
    }

    // Load more reviews
    if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', function() {
            const page = this.dataset.page;
            loadReviews(page);
        });
    }

    // Delete review
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('delete-review-btn')) {
            e.preventDefault();

            if (confirm('Are you sure you want to delete this review?')) {
                const reviewId = e.target.dataset.reviewId;

                fetch('/reviews/delete/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                    },
                    body: `review_id=${reviewId}`
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Update rating display
                        const ratingStars = document.getElementById('rating-stars');
                        const avgRating = document.getElementById('avg-rating');
                        const totalReviews = document.getElementById('total-reviews');

                        if (ratingStars) ratingStars.innerHTML = data.stars_html;
                        if (avgRating) avgRating.textContent = data.new_avg;
                        if (totalReviews) totalReviews.textContent = data.total_reviews;

                        // Remove review from DOM
                        const reviewCard = e.target.closest('.review-card');
                        if (reviewCard) {
                            reviewCard.remove();
                        }

                        showToast(data.message, 'success');
                    } else {
                        showToast(data.error, 'error');
                    }
                })
                .catch(error => {
                    showToast('An error occurred. Please try again.', 'error');
                    console.error('Error:', error);
                });
            }
        }
    });

    // Submit comment
    document.addEventListener('submit', function(e) {
        if (e.target.classList.contains('comment-form')) {
            e.preventDefault();

            const formData = new FormData(e.target);
            const reviewId = formData.get('review_id');

            fetch('/reviews/comment/submit/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Add comment to DOM
                    const commentsContainer = document.querySelector(`#comments-${reviewId}`);
                    if (commentsContainer) {
                        commentsContainer.insertAdjacentHTML('beforeend', data.comment_html);
                    }

                    // Reset form
                    e.target.reset();

                    showToast(data.message, 'success');
                } else {
                    showToast(data.error, 'error');
                }
            })
            .catch(error => {
                showToast('An error occurred. Please try again.', 'error');
                console.error('Error:', error);
            });
        }
    });

    // Helper function to load reviews
    function loadReviews(page) {
        const productId = window.PRODUCT_ID; // We'll set this in the template

        if (!productId) {
            console.error('Product ID not found');
            return;
        }

        fetch(`/reviews/load/${productId}/?page=${page}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const reviewsContainer = document.getElementById('reviews-container');
                if (reviewsContainer) {
                    if (page === 1) {
                        reviewsContainer.innerHTML = data.reviews_html;
                    } else {
                        reviewsContainer.insertAdjacentHTML('beforeend', data.reviews_html);
                    }
                }

                // Update load more button
                if (loadMoreBtn) {
                    if (data.has_next) {
                        loadMoreBtn.dataset.page = data.current_page + 1;
                    } else {
                        loadMoreBtn.style.display = 'none';
                    }
                }
            }
        })
        .catch(error => {
            console.error('Error loading reviews:', error);
        });
    }

    // Helper function to show toast notifications
    function showToast(message, type) {
        const toast = document.getElementById('alert-toast');
        const toastMessage = document.getElementById('toast-message');

        if (toast && toastMessage) {
            toastMessage.textContent = message;
            toast.className = `toast ${type === 'success' ? 'bg-success' : 'bg-danger'} text-white`;

            // Check if Bootstrap is available
            if (typeof bootstrap !== 'undefined') {
                const bsToast = new bootstrap.Toast(toast);
                bsToast.show();
            } else {
                // Fallback: show toast manually
                toast.style.display = 'block';
                setTimeout(() => {
                    toast.style.display = 'none';
                }, 3000);
            }
        } else {
            // Fallback: use alert
            alert(message);
        }
    }
});

// Chat System
document.addEventListener('DOMContentLoaded', function() {
    const chatMessages = document.getElementById('chatMessages');
    const chatForm = document.getElementById('chatForm');
    const messageInput = chatForm ? chatForm.querySelector('input[name="message"]') : null;
    const typingIndicator = document.querySelector('.typing-indicator');

    if (!chatMessages || !chatForm) {
        return; // Chat system not present on this page
    }

    // Auto-scroll to bottom
    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Initial scroll
    scrollToBottom();

    // Enhanced form submission with loading state
    chatForm.addEventListener('submit', function(e) {
        const submitBtn = this.querySelector('.enhanced-send-btn');
        const message = messageInput ? messageInput.value.trim() : '';

        if (!message) {
            e.preventDefault();
            return;
        }

        // Add loading state
        if (submitBtn) {
            submitBtn.classList.add('form-loading');
            submitBtn.disabled = true;
        }

        // Show typing indicator briefly
        if (typingIndicator) {
            typingIndicator.classList.remove('d-none');
            setTimeout(() => {
                typingIndicator.classList.add('d-none');
            }, 1000);
        }
    });

    // Enter key to send message
    if (messageInput) {
        messageInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const submitEvent = new Event('submit', { cancelable: true });
                chatForm.dispatchEvent(submitEvent);
            }
        });
    }

    // Add smooth scroll behavior for new messages
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                scrollToBottom();
            }
        });
    });

    observer.observe(chatMessages, { childList: true, subtree: true });

    // Animate existing messages on load
    document.querySelectorAll('.message-container').forEach((msg, index) => {
        msg.style.animationDelay = `${index * 0.1}s`;
    });
});

// Chat Box Toggle Function
function toggleChatBox() {
    const chatBox = document.getElementById('chatBox');
    if (!chatBox) return;

    if (chatBox.classList.contains('d-none')) {
        chatBox.classList.remove('d-none');
        chatBox.style.animation = 'chatSlideIn 0.5s ease-out';
    } else {
        chatBox.style.animation = 'chatSlideIn 0.5s ease-out reverse';
        setTimeout(() => {
            chatBox.classList.add('d-none');
        }, 500);
    }
}

// Simulate periodic status updates (optional)
setInterval(() => {
    const statusDot = document.querySelector('.status-dot');
    if (statusDot) {
        statusDot.style.background = Math.random() > 0.9 ? '#ffc107' : '#ffffff';
    }
}, 10000);

// Product Description and Specifications Toggle
document.addEventListener('DOMContentLoaded', function () {
    // Description toggle
    const descCollapse = document.getElementById('fullDescription');
    const descShort = document.getElementById('descShort');
    const toggleDescBtn = document.getElementById('toggleDescBtn');

    if (descCollapse && descShort && toggleDescBtn) {
        descCollapse.addEventListener('show.bs.collapse', function () {
            descShort.style.display = 'none';
            toggleDescBtn.textContent = 'Show Less';
        });

        descCollapse.addEventListener('hidden.bs.collapse', function () {
            descShort.style.display = 'block';
            toggleDescBtn.textContent = 'Show More';
        });
    }

    // Specifications toggle
    const specCollapse = document.getElementById('specCollapse');
    const specShort = document.getElementById('specShort');
    const toggleSpecBtn = document.getElementById('toggleSpecBtn');

    if (specCollapse && specShort && toggleSpecBtn) {
        specCollapse.addEventListener('show.bs.collapse', function () {
            specShort.style.display = 'none';
            toggleSpecBtn.textContent = 'Show Less';
        });

        specCollapse.addEventListener('hidden.bs.collapse', function () {
            specShort.style.display = 'block';
            toggleSpecBtn.textContent = 'Show More';
        });
    }
});

// Global error handler for AJAX requests
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});

// Utility function to get CSRF token
function getCSRFToken() {
    const token = document.querySelector('[name=csrfmiddlewaretoken]');
    return token ? token.value : '';
}

// Export functions for use in other scripts if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        toggleChatBox,
        getCSRFToken
    };
}