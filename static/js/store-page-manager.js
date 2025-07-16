/**
 * Enhanced Store Page Manager
 * Handles all store page interactions, navigation, and functionality
 */
class StorePageManager {
  constructor() {
    this.config = {
      animationDuration: 300,
      scrollOffset: 120,
      debounceDelay: 250,
      toastDuration: 5000,
      apiEndpoints: {
        toggleFavorite: '/stores/toggle-favorite/',
        addToCart: '/cart/add/',
        addToWishlist: '/wishlist/add/',
        quickView: '/products/quick-view/',
        contact: '/stores/contact/',
        newsletter: '/newsletter/subscribe/',
        review: '/stores/review/'
      }
    };
    
    this.state = {
      isLoading: false,
      currentView: 'grid',
      currentSort: 'newest',
      favorites: new Set(),
      cart: new Map(),
      wishlist: new Set()
    };
    
    this.elements = {};
    this.observers = new Map();
    this.init();
  }

  /**
   * Initialize the store page manager
   */
  init() {
    try {
      this.cacheElements();
      this.loadInitialData();
      this.setupEventListeners();
      this.setupObservers();
      this.setupAccessibility();
      this.setupPerformanceMonitoring();
      this.loadUserPreferences();
      this.initializeAnalytics();
    } catch (error) {
      this.handleError('Failed to initialize store page', error);
    }
  }

  /**
   * Cache DOM elements for better performance
   */
  cacheElements() {
    this.elements = {
      // Navigation
      storeNav: document.getElementById('storeNav'),
      navLinks: document.querySelectorAll('#storeNav button[data-section]'),
      
      // Products
      productsContainer: document.getElementById('productsContainer'),
      sortSelect: document.getElementById('sortProducts'),
      viewToggle: document.querySelectorAll('[data-view]'),
      productCards: document.querySelectorAll('.product-card'),
      
      // Store info
      storeWrapper: document.getElementById('storeWrapper') || document.querySelector('.store-page'),
      favoriteButton: document.querySelector('.btn-follow'),
      favoriteIcon: document.getElementById('favoriteIcon'),
      contactButton: document.querySelector('.btn-contact'),
      
      // Modals
      contactModal: document.getElementById('contactModal'),
      quickViewModal: document.getElementById('quickViewModal'),
      
      // Forms
      contactForm: document.getElementById('contactForm'),
      newsletterForm: document.querySelector('.newsletter-form'),
      
      // UI elements
      loadingSpinner: document.getElementById('loadingSpinner'),
      successToast: document.getElementById('successToast'),
      errorToast: document.getElementById('errorToast'),
      backToTop: document.getElementById('backToTop'),
      
      // Sections
      sections: {
        products: document.getElementById('products'),
        about: document.getElementById('about'),
        reviews: document.getElementById('reviews'),
        contact: document.getElementById('contact')
      }
    };
  }

  /**
   * Load initial data from DOM
   */
  loadInitialData() {
    const wrapper = this.elements.storeWrapper;
    if (wrapper) {
      this.storeId = wrapper.dataset.storeId;
      this.storeName = wrapper.dataset.storeName || document.querySelector('.store-name')?.textContent;
      this.storeDescription = wrapper.dataset.storeDescription || document.querySelector('.store-tagline')?.textContent;
    }
  }

  /**
   * Setup all event listeners
   */
  setupEventListeners() {
    // Navigation
    this.setupNavigation();
    
    // Product interactions
    this.setupProductSorting();
    this.setupViewToggle();
    this.setupProductActions();
    
    // Store actions
    this.setupStoreActions();
    
    // Forms
    this.setupForms();
    
    // Keyboard navigation
    this.setupKeyboardNavigation();
    
    // Scroll events
    this.setupScrollEvents();
    
    // Resize events
    this.setupResizeHandler();
  }

  /**
   * Setup navigation functionality
   */
  setupNavigation() {
    this.elements.navLinks.forEach(link => {
      link.addEventListener('click', this.debounce((e) => {
        e.preventDefault();
        const sectionId = link.getAttribute('data-section');
        this.scrollToSection(sectionId);
        this.updateActiveNav(link);
        this.trackEvent('navigation', 'section_click', sectionId);
      }, this.config.debounceDelay));
    });
  }

  /**
   * Scroll to a specific section with smooth animation
   */
  scrollToSection(sectionId) {
    const section = this.elements.sections[sectionId];
    if (!section) return;

    const offset = this.config.scrollOffset;
    const elementPosition = section.getBoundingClientRect().top;
    const offsetPosition = elementPosition + window.pageYOffset - offset;

    window.scrollTo({
      top: offsetPosition,
      behavior: 'smooth'
    });

    // Update URL hash without triggering scroll
    history.replaceState(null, null, `#${sectionId}`);
  }

  /**
   * Update active navigation state
   */
  updateActiveNav(activeLink) {
    this.elements.navLinks.forEach(link => {
      link.classList.remove('active');
      link.setAttribute('aria-selected', 'false');
    });
    
    activeLink.classList.add('active');
    activeLink.setAttribute('aria-selected', 'true');
  }

  /**
   * Setup scroll spy with Intersection Observer
   */
  setupObservers() {
    // Section scroll spy
    const sectionObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const sectionId = entry.target.id;
          const link = document.querySelector(`#storeNav button[data-section="${sectionId}"]`);
          if (link) this.updateActiveNav(link);
        }
      });
    }, {
      root: null,
      rootMargin: '-120px 0px -50% 0px',
      threshold: 0.1
    });

    Object.values(this.elements.sections).forEach(section => {
      if (section) sectionObserver.observe(section);
    });

    // Lazy loading observer
    this.setupLazyLoading();

    // Animation observer
    this.setupAnimationObserver();
  }

  /**
   * Setup lazy loading for images
   */
  setupLazyLoading() {
    const imageObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const img = entry.target;
          this.loadImage(img);
          imageObserver.unobserve(img);
        }
      });
    }, {
      rootMargin: '50px 0px'
    });

    document.querySelectorAll('img[data-src]').forEach(img => {
      imageObserver.observe(img);
    });
  }

  /**
   * Load image with error handling
   */
  loadImage(img) {
    const tempImg = new Image();
    tempImg.onload = () => {
      img.src = img.dataset.src;
      img.classList.add('loaded');
      img.removeAttribute('data-src');
    };
    tempImg.onerror = () => {
      img.src = '/static/images/placeholder.jpg';
      img.classList.add('error');
    };
    tempImg.src = img.dataset.src;
  }

  /**
   * Setup animation observer for scroll-triggered animations
   */
  setupAnimationObserver() {
    const animationObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('animate-in');
        }
      });
    }, {
      threshold: 0.1
    });

    document.querySelectorAll('.animate-on-scroll').forEach(el => {
      animationObserver.observe(el);
    });
  }

  /**
   * Setup product sorting functionality
   */
  setupProductSorting() {
    if (!this.elements.sortSelect) return;

    this.elements.sortSelect.addEventListener('change', (e) => {
      this.state.currentSort = e.target.value;
      this.sortProducts(e.target.value);
      this.trackEvent('products', 'sort_change', e.target.value);
    });
  }

  /**
   * Sort products based on selected criteria
   */
  sortProducts(type) {
    const container = this.elements.productsContainer;
    if (!container) return;

    this.showLoading();
    
    // Add loading state
    container.classList.add('sorting');
    
    setTimeout(() => {
      const products = Array.from(container.children);
      const sortedProducts = this.getSortedProducts(products, type);
      
      // Remove all products
      products.forEach(p => p.remove());
      
      // Add sorted products back
      sortedProducts.forEach(product => {
        container.appendChild(product);
      });
      
      container.classList.remove('sorting');
      this.hideLoading();
      
      // Trigger animation
      this.animateProductGrid();
    }, 150);
  }

  /**
   * Get sorted products array
   */
  getSortedProducts(products, type) {
    return products.sort((a, b) => {
      switch (type) {
        case 'price-low':
          return this.getPrice(a) - this.getPrice(b);
        case 'price-high':
          return this.getPrice(b) - this.getPrice(a);
        case 'popular':
          return this.getRating(b) - this.getRating(a);
        case 'rating':
          return this.getAverageRating(b) - this.getAverageRating(a);
        case 'newest':
        default:
          return this.getDateAdded(b) - this.getDateAdded(a);
      }
    });
  }

  /**
   * Extract price from product element
   */
  getPrice(product) {
    const priceEl = product.querySelector('.price-current');
    if (!priceEl) return 0;
    return parseFloat(priceEl.textContent.replace(/[^\d.]/g, '')) || 0;
  }

  /**
   * Extract rating count from product element
   */
  getRating(product) {
    const ratingEl = product.querySelector('.rating-count');
    if (!ratingEl) return 0;
    const match = ratingEl.textContent.match(/\((\d+)\)/);
    return match ? parseInt(match[1]) : 0;
  }

  /**
   * Extract average rating from product element
   */
  getAverageRating(product) {
    const stars = product.querySelectorAll('.stars .fas.fa-star');
    return stars.length;
  }

  /**
   * Extract date added from product element
   */
  getDateAdded(product) {
    const dateEl = product.querySelector('[data-date]');
    return dateEl ? new Date(dateEl.dataset.date).getTime() : 0;
  }

  /**
   * Setup view toggle functionality
   */
  setupViewToggle() {
    this.elements.viewToggle.forEach(button => {
      button.addEventListener('click', (e) => {
        e.preventDefault();
        const viewType = button.dataset.view;
        this.toggleProductView(viewType);
        this.trackEvent('products', 'view_change', viewType);
      });
    });
  }

  /**
   * Toggle between grid and list view
   */
  toggleProductView(viewType) {
    const container = this.elements.productsContainer;
    if (!container) return;

    this.state.currentView = viewType;
    
    // Update button states
    this.elements.viewToggle.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === viewType);
    });
    
    // Update container classes
    container.classList.toggle('list-view', viewType === 'list');
    container.classList.toggle('grid-view', viewType === 'grid');
    
    // Save preference
    localStorage.setItem('store_view_preference', viewType);
    
    // Animate transition
    this.animateProductGrid();
  }

  /**
   * Animate product grid changes
   */
  animateProductGrid() {
    const products = this.elements.productsContainer?.children;
    if (!products) return;

    Array.from(products).forEach((product, index) => {
      product.style.opacity = '0';
      product.style.transform = 'translateY(20px)';
      
      setTimeout(() => {
        product.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        product.style.opacity = '1';
        product.style.transform = 'translateY(0)';
      }, index * 50);
    });
  }

  /**
   * Setup product action buttons
   */
  setupProductActions() {
    document.addEventListener('click', (e) => {
      const target = e.target.closest('[data-action]');
      if (!target) return;

      const action = target.dataset.action;
      const productId = target.dataset.productId;

      switch (action) {
        case 'add-to-cart':
          this.addToCart(productId, target);
          break;
        case 'add-to-wishlist':
          this.addToWishlist(productId, target);
          break;
        case 'quick-view':
          this.showQuickView(productId);
          break;
        case 'share-product':
          this.shareProduct(productId);
          break;
      }
    });
  }

  /**
   * Share product
   */
  async shareProduct(productId) {
    try {
      const product = document.querySelector(`[data-product-id="${productId}"]`);
      const productName = product?.querySelector('.product-name')?.textContent;
      const productUrl = `${window.location.origin}/products/${productId}/`;
      
      const shareData = {
        title: productName || 'Check out this product',
        text: `Found this amazing product at ${this.storeName}`,
        url: productUrl
      };

      if (navigator.share && navigator.canShare(shareData)) {
        await navigator.share(shareData);
        this.trackEvent('engagement', 'product_share', productId);
      } else {
        await navigator.clipboard.writeText(productUrl);
        this.showToast('Product link copied to clipboard!', 'success');
      }
    } catch (error) {
      this.handleError('Failed to share product', error);
    }
  }

  /**
   * Setup store actions
   */
  setupStoreActions() {
    // Favorite toggle
    this.elements.favoriteButton?.addEventListener('click', (e) => {
      e.preventDefault();
      this.toggleFavorite();
    });

    // Share store
    document.addEventListener('click', (e) => {
      if (e.target.matches('[onclick*="shareStore"]') || e.target.closest('[onclick*="shareStore"]')) {
        e.preventDefault();
        this.shareStore();
      }
    });
  }

  /**
   * Toggle store favorite status
   */
  async toggleFavorite() {
    if (!this.storeId) return;

    const icon = this.elements.favoriteIcon;
    const button = this.elements.favoriteButton;
    
    if (!icon || !button) return;

    try {
      this.updateButtonState(button, 'loading');
      
      const response = await this.apiRequest('POST', `${this.config.apiEndpoints.toggleFavorite}${this.storeId}/`);
      
      if (response.success) {
        const isFollowing = response.is_following;
        
        // Update icon
        icon.classList.toggle('fas', isFollowing);
        icon.classList.toggle('far', !isFollowing);
        
        // Update button text
        const btnText = button.querySelector('.btn-text');
        if (btnText) {
          btnText.textContent = isFollowing ? 'Following' : 'Follow';
        }
        
        // Update state
        if (isFollowing) {
          this.state.favorites.add(this.storeId);
        } else {
          this.state.favorites.delete(this.storeId);
        }
        
        this.updateButtonState(button, 'success');
        this.showToast(
          isFollowing ? 'Store added to favorites!' : 'Store removed from favorites!',
          'success'
        );
        this.trackEvent('engagement', 'store_favorite', this.storeId);
      } else {
        throw new Error(response.message || 'Failed to update favorite status');
      }
    } catch (error) {
      this.updateButtonState(button, 'error');
      this.handleError('Failed to update favorite status', error);
    }
  }

  /**
   * Share store
   */
  async shareStore() {
    try {
      const shareData = {
        title: this.storeName || 'Check out this store',
        text: this.storeDescription || 'Found this amazing store',
        url: window.location.href
      };

      if (navigator.share && navigator.canShare(shareData)) {
        await navigator.share(shareData);
        this.trackEvent('engagement', 'store_share', this.storeId);
      } else {
        await navigator.clipboard.writeText(window.location.href);
        this.showToast('Store link copied to clipboard!', 'success');
      }
    } catch (error) {
      this.handleError('Failed to share store', error);
    }
  }

  /**
   * Setup form handling
   */
  setupForms() {
    // Contact form
    if (this.elements.contactForm) {
      this.elements.contactForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.submitContactForm();
      });
    }

    // Newsletter form
    if (this.elements.newsletterForm) {
      this.elements.newsletterForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.submitNewsletterForm();
      });
    }
  }

  /**
   * Submit contact form
   */
  async submitContactForm() {
    const form = this.elements.contactForm;
    if (!form || !this.validateForm(form)) return;

    try {
      this.showLoading();
      
      const formData = new FormData(form);
      const response = await this.apiRequest('POST', `${this.config.apiEndpoints.contact}${this.storeId}/`, formData);
      
      if (response.success) {
        this.showToast('Message sent successfully!', 'success');
        form.reset();
        
        // Hide modal
        const modal = bootstrap.Modal.getInstance(this.elements.contactModal);
        modal?.hide();
        
        this.trackEvent('engagement', 'contact_form', this.storeId);
      } else {
        throw new Error(response.message || 'Failed to send message');
      }
    } catch (error) {
      this.handleError('Failed to send message', error);
    } finally {
      this.hideLoading();
    }
  }

  /**
   * Submit newsletter form
   */
  async submitNewsletterForm() {
    const form = this.elements.newsletterForm;
    if (!form || !this.validateForm(form)) return;

    try {
      const submitButton = form.querySelector('button[type="submit"]');
      this.updateButtonState(submitButton, 'loading');
      
      const formData = new FormData(form);
      formData.append('store_id', this.storeId);
      
      const response = await this.apiRequest('POST', this.config.apiEndpoints.newsletter, formData);
      
      if (response.success) {
        this.showToast('Successfully subscribed to newsletter!', 'success');
        form.reset();
        this.updateButtonState(submitButton, 'success');
        this.trackEvent('engagement', 'newsletter_signup', this.storeId);
      } else {
        throw new Error(response.message || 'Failed to subscribe');
      }
    } catch (error) {
      this.handleError('Failed to subscribe to newsletter', error);
    }
  }

  /**
   * Validate form
   */
  validateForm(form) {
    const inputs = form.querySelectorAll('[required]');
    let isValid = true;

    inputs.forEach(input => {
      if (!input.value.trim()) {
        this.showFieldError(input, 'This field is required');
        isValid = false;
      } else if (input.type === 'email' && !this.isValidEmail(input.value)) {
        this.showFieldError(input, 'Please enter a valid email address');
        isValid = false;
      } else {
        this.clearFieldError(input);
      }
    });

    return isValid;
  }

  /**
   * Show field error
   */
  showFieldError(input, message) {
    input.classList.add('is-invalid');
    const feedback = input.nextElementSibling;
    if (feedback && feedback.classList.contains('invalid-feedback')) {
      feedback.textContent = message;
    }
  }

  /**
   * Clear field error
   */
  clearFieldError(input) {
    input.classList.remove('is-invalid');
  }

  /**
   * Validate email format
   */
  isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  }

  /**
   * Setup enhanced accessibility
   */
  setupAccessibility() {
    // Keyboard navigation
    document.addEventListener('keydown', (e) => {
      switch (e.key) {
        case 'Escape':
          this.handleEscapeKey();
          break;
        case 'Tab':
          this.handleTabKey(e);
          break;
        case 'Enter':
        case ' ':
          this.handleActivation(e);
          break;
      }
    });

    // Focus management
    document.addEventListener('focusin', (e) => {
      if (e.target.matches('button, a, input, select, textarea')) {
        e.target.classList.add('focus-visible');
      }
    });

    document.addEventListener('focusout', (e) => {
      e.target.classList.remove('focus-visible');
    });

    // Announce dynamic content changes
    this.setupAriaLive();
  }

  /**
   * Handle escape key
   */
  handleEscapeKey() {
    // Close modals
    document.querySelectorAll('.modal.show').forEach(modal => {
      const modalInstance = bootstrap.Modal.getInstance(modal);
      modalInstance?.hide();
    });

    // Clear search/filters
    const activeSearch = document.querySelector('.search-input:focus');
    if (activeSearch) {
      activeSearch.blur();
    }
  }

  /**
   * Handle tab key for focus trap
   */
  handleTabKey(e) {
    const modal = document.querySelector('.modal.show');
    if (modal) {
      const focusableElements = modal.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (e.shiftKey && document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      } else if (!e.shiftKey && document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    }
  }

  /**
   * Handle activation (Enter/Space)
   */
  handleActivation(e) {
    if (e.target.matches('button, [role="button"]')) {
      e.preventDefault();
      e.target.click();
    }
  }

  /**
   * Setup ARIA live regions
   */
  setupAriaLive() {
    // Create live region for announcements
    const liveRegion = document.createElement('div');
    liveRegion.setAttribute('aria-live', 'polite');
    liveRegion.setAttribute('aria-atomic', 'true');
    liveRegion.className = 'sr-only';
    liveRegion.id = 'aria-live-region';
    document.body.appendChild(liveRegion);
  }

  /**
   * Announce message to screen readers
   */
  announceToScreenReader(message) {
    const liveRegion = document.getElementById('aria-live-region');
    if (liveRegion) {
      liveRegion.textContent = message;
      setTimeout(() => {
        liveRegion.textContent = '';
      }, 1000);
    }
  }

  /**
   * Setup keyboard navigation
   */
  setupKeyboardNavigation() {
    // Arrow key navigation for product grid
    document.addEventListener('keydown', (e) => {
      if (e.target.closest('.products-grid')) {
        this.handleGridNavigation(e);
      }
    });
  }

  /**
   * Handle grid navigation with arrow keys
   */
  handleGridNavigation(e) {
    const products = Array.from(this.elements.productsContainer?.children || []);
    const currentIndex = products.indexOf(document.activeElement.closest('.product-card'));
    
    if (currentIndex === -1) return;

    let newIndex;
    const columns = this.getGridColumns();

    switch (e.key) {
      case 'ArrowUp':
        newIndex = currentIndex - columns;
        break;
      case 'ArrowDown':
        newIndex = currentIndex + columns;
        break;
      case 'ArrowLeft':
        newIndex = currentIndex - 1;
        break;
      case 'ArrowRight':
        newIndex = currentIndex + 1;
        break;
      default:
        return;
    }

    if (newIndex >= 0 && newIndex < products.length) {
      e.preventDefault();
      const targetProduct = products[newIndex];
      const focusableElement = targetProduct.querySelector('a, button');
      focusableElement?.focus();
    }
  }

  /**
   * Get number of columns in grid
   */
  getGridColumns() {
    const container = this.elements.productsContainer;
    if (!container) return 1;

    const firstProduct = container.firstElementChild;
    if (!firstProduct) return 1;

    const containerWidth = container.offsetWidth;
    const productWidth = firstProduct.offsetWidth;
    const gap = 20; // Approximate gap between products

    return Math.floor(containerWidth / (productWidth + gap));
  }

  /**
   * Setup scroll events
   */
  setupScrollEvents() {
    let scrollTimeout;
    
    window.addEventListener('scroll', () => {
      clearTimeout(scrollTimeout);
      scrollTimeout = setTimeout(() => {
        this.handleScroll();
      }, 16); // ~60fps
    });
  }

  /**
   * Handle scroll events
   */
  handleScroll() {
    const scrollY = window.pageYOffset;
    
    // Back to top button
    const backToTop = this.elements.backToTop;
    if (backToTop) {
      backToTop.classList.toggle('show', scrollY > 300);
    }

    // Header background opacity
    const header = document.querySelector('.store-header');
    if (header) {
      const opacity = Math.min(scrollY / 200, 1);
      header.style.setProperty('--scroll-opacity', opacity);
    }
  }

  /**
   * Setup resize handler
   */
  setupResizeHandler() {
    let resizeTimeout;
    
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        this.handleResize();
      }, 250);
    });
  }

  /**
   * Handle window resize
   */
  handleResize() {
    // Update grid calculations
    this.updateGridLayout();
    
    // Update mobile navigation
    this.updateMobileNav();
  }

  /**
   * Update grid layout
   */
  updateGridLayout() {
    const container = this.elements.productsContainer;
    if (!container) return;

    const columns = this.getGridColumns();
    container.style.setProperty('--grid-columns', columns);
  }

  /**
   * Update mobile navigation
   */
  updateMobileNav() {
    const nav = this.elements.storeNav;
    if (!nav) return;

    const isMobile = window.innerWidth < 768;
    nav.classList.toggle('mobile', isMobile);
  }

  /**
   * Setup performance monitoring
   */
  setupPerformanceMonitoring() {
    // Monitor page load time
    window.addEventListener('load', () => {
      const loadTime = performance.timing.loadEventEnd - performance.timing.navigationStart;
      this.trackEvent('performance', 'page_load_time', Math.round(loadTime));
    });

    // Monitor largest contentful paint
    if ('PerformanceObserver' in window) {
      try {
        const observer = new PerformanceObserver((entries) => {
          entries.getEntries().forEach(entry => {
            if (entry.entryType === 'largest-contentful-paint') {
              this.trackEvent('performance', 'lcp', Math.round(entry.startTime));
            }
          });
        });
        observer.observe({ type: 'largest-contentful-paint', buffered: true });
      } catch (error) {
        console.warn('Performance observer not supported', error);
      }
    }
  }

  /**
   * Load user preferences
   */
  loadUserPreferences() {
    // Load view preference
    const viewPreference = localStorage.getItem('store_view_preference');
    if (viewPreference && ['grid', 'list'].includes(viewPreference)) {
      this.toggleProductView(viewPreference);
    }

    // Load sort preference
    const sortPreference = localStorage.getItem('store_sort_preference');
    if (sortPreference && this.elements.sortSelect) {
      this.elements.sortSelect.value = sortPreference;
      this.state.currentSort = sortPreference;
    }
  }

  /**
   * Initialize analytics
   */
  initializeAnalytics() {
    // Track page view
    this.trackEvent('page_view', 'store_page', this.storeId);

    // Track time on page
    this.startTime = Date.now();
    
    window.addEventListener('beforeunload', () => {
      const timeOnPage = Math.round((Date.now() - this.startTime) / 1000);
      this.trackEvent('engagement', 'time_on_page', timeOnPage);
    });
  }

  /**
   * Track analytics event
   */
  trackEvent(category, action, label, value) {
    if (typeof gtag !== 'undefined') {
      gtag('event', action, {
        event_category: category,
        event_label: label,
        value: value
      });
    }
  }

  /**
   * Make API request
   */
  async apiRequest(method, url, data = null) {
    const options = {
      method,
      headers: {
        'X-CSRFToken': this.getCSRFToken(),
        'X-Requested-With': 'XMLHttpRequest'
      }
    };

    if (data) {
      if (data instanceof FormData) {
        options.body = data;
      } else {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(data);
      }
    }

    const response = await fetch(url, options);
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return await response.json();
  }

  /**
   * Get CSRF token
   */
  getCSRFToken() {
    const token = document.querySelector('[name=csrfmiddlewaretoken]');
    return token ? token.value : '';
  }

  /**
   * Update button state
   */
  updateButtonState(button, state) {
    if (!button) return;

    button.classList.remove('loading', 'success', 'error');
    button.disabled = false;

    switch (state) {
      case 'loading':
        button.classList.add('loading');
        button.disabled = true;
        break;
      case 'success':
        button.classList.add('success');
        setTimeout(() => {
          button.classList.remove('success');
        }, 2000);
        break;
      case 'error':
        button.classList.add('error');
        setTimeout(() => {
          button.classList.remove('error');
        }, 3000);
        break;
    }
  }


  /**
   * Show loading spinner
   */
  showLoading() {
    this.state.isLoading = true;
    const loader = this.elements.loadingSpinner;
    if (loader) {
      loader.style.display = 'flex';
      loader.setAttribute('aria-hidden', 'false');
    }
  }

  /**
   * Hide loading spinner
   */
  hideLoading() {
    this.state.isLoading = false;
    const loader = this.elements.loadingSpinner;
    if (loader) {
      loader.style.display = 'none';
      loader.setAttribute('aria-hidden', 'true');
    }
  }

  /**
   * Show toast notification
   */
  showToast(message, type = 'success') {
    const toastElement = this.elements[`${type}Toast`];
    if (!toastElement) return;

    const toastBody = toastElement.querySelector('.toast-body');
    if (toastBody) {
      toastBody.textContent = message;
    }

    const toast = bootstrap.Toast.getOrCreateInstance(toastElement, {
      delay: this.config.toastDuration
    });
    toast.show();

    // Announce to screen readers
    this.announceToScreenReader(message);
  }

  /**
   * Handle errors
   */
  handleError(message, error) {
    console.error(message, error);
    this.showToast(message, 'error');
    this.trackEvent('error', 'javascript_error', message);
  }

  /**
   * Debounce function
   */
  debounce(func, wait) {
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

  /**
   * Cleanup method
   */
  destroy() {
    // Remove event listeners
    this.observers.forEach(observer => observer.disconnect());
    this.observers.clear();
    
    // Clear timeouts
    clearTimeout(this.scrollTimeout);
    clearTimeout(this.resizeTimeout);
    
    // Remove from global scope
    delete window.storeManager;
  }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.storeManager = new StorePageManager();
});

// Global functions for backwards compatibility
window.toggleFavorite = (storeId) => {
  window.storeManager?.toggleFavorite(storeId);
};

window.shareStore = () => {
  window.storeManager?.shareStore();
};


window.shareProduct = (productId) => {
  window.storeManager?.shareProduct(productId);
};

window.subscribeNewsletter = (event) => {
  event.preventDefault();
  window.storeManager?.submitNewsletterForm();
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = StorePageManager;
}