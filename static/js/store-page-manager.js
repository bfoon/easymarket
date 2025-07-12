class StorePageManager {
  constructor() {
    this.init();
  }

  init() {
    this.setupNavigation();
    this.setupScrollSpy();
    this.setupProductSorting();
    this.setupAccessibility();
    this.setupToast();
    this.storeId = document.getElementById('storeWrapper')?.dataset?.storeId;
    this.storeName = document.getElementById('storeWrapper')?.dataset?.storeName;
    this.storeDescription = document.getElementById('storeWrapper')?.dataset?.storeDescription;
  }

  setupNavigation() {
    const navLinks = document.querySelectorAll('#storeNav a[data-section]');
    navLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const sectionId = link.getAttribute('data-section');
        this.scrollToSection(sectionId);
        this.updateActiveNav(link);
      });
    });
  }

  scrollToSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (section) {
      const offset = 120;
      const elementPosition = section.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.pageYOffset - offset;
      window.scrollTo({ top: offsetPosition, behavior: 'smooth' });
    }
  }

  updateActiveNav(activeLink) {
    document.querySelectorAll('#storeNav .nav-link').forEach(link => {
      link.classList.remove('active');
      link.setAttribute('aria-selected', 'false');
    });
    activeLink.classList.add('active');
    activeLink.setAttribute('aria-selected', 'true');
  }

  setupScrollSpy() {
    const sections = ['products', 'about', 'reviews', 'contact'];
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const sectionId = entry.target.id;
          const link = document.querySelector(`#storeNav a[data-section="${sectionId}"]`);
          if (link) this.updateActiveNav(link);
        }
      });
    }, {
      root: null,
      rootMargin: '-120px 0px -50% 0px',
      threshold: 0
    });

    sections.forEach(id => {
      const section = document.getElementById(id);
      if (section) observer.observe(section);
    });
  }

  setupProductSorting() {
    const sortSelect = document.getElementById('sortProducts');
    if (sortSelect) {
      sortSelect.addEventListener('change', (e) => this.sortProducts(e.target.value));
    }
  }

  sortProducts(type) {
    const container = document.getElementById('productsContainer');
    const products = Array.from(container.children);
    products.sort((a, b) => {
      switch (type) {
        case 'price-low': return this.getPrice(a) - this.getPrice(b);
        case 'price-high': return this.getPrice(b) - this.getPrice(a);
        case 'popular': return this.getRating(b) - this.getRating(a);
        default: return 0;
      }
    });
    products.forEach(p => container.appendChild(p));
  }

  getPrice(product) {
    const el = product.querySelector('.price-current');
    return parseFloat(el?.textContent.replace(/[^\d.]/g, '')) || 0;
  }

  getRating(product) {
    const el = product.querySelector('.rating-count');
    const match = el?.textContent.match(/\d+/);
    return match ? parseInt(match[0]) : 0;
  }

  setupAccessibility() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal.show').forEach(modal => {
          bootstrap.Modal.getInstance(modal)?.hide();
        });
      }
    });

    document.addEventListener('focusin', (e) => {
      if (e.target.matches('button, a, input, select, textarea')) {
        e.target.classList.add('focus-visible');
      }
    });

    document.addEventListener('focusout', (e) => {
      e.target.classList.remove('focus-visible');
    });
  }

  setupToast() {
    this.toastElement = document.getElementById('successToast');
    if (this.toastElement) {
      this.toast = new bootstrap.Toast(this.toastElement);
    }
  }

  showToast(message) {
    const body = this.toastElement?.querySelector('.toast-body');
    if (body) {
      body.textContent = message;
      this.toast?.show();
    }
  }

  showLoading() {
    const loader = document.getElementById('loadingSpinner');
    if (loader) loader.style.display = 'flex';
  }

  hideLoading() {
    const loader = document.getElementById('loadingSpinner');
    if (loader) loader.style.display = 'none';
  }

  async toggleFavorite() {
    const icon = document.getElementById('favoriteIcon');
    const button = icon?.closest('.btn-follow');
    if (!this.storeId || !icon || !button) return;

    try {
      this.showLoading();
      const res = await fetch(`/stores/toggle-favorite/${this.storeId}/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
          'Content-Type': 'application/json',
        },
      });
      const data = await res.json();
      if (data.success) {
        icon.classList.toggle('fas', data.is_following);
        icon.classList.toggle('far', !data.is_following);
        button.querySelector('.btn-text').textContent = data.is_following ? 'Following' : 'Follow';
        this.showToast(data.is_following ? 'Store added to favorites!' : 'Store removed from favorites.');
      }
    } catch (e) {
      console.error(e);
      this.showToast('Failed to update favorite status.');
    } finally {
      this.hideLoading();
    }
  }

  async shareStore() {
    try {
      const shareData = {
        title: this.storeName,
        text: this.storeDescription,
        url: window.location.href
      };

      if (navigator.share && navigator.canShare(shareData)) {
        await navigator.share(shareData);
      } else {
        await navigator.clipboard.writeText(window.location.href);
        this.showToast('Store link copied to clipboard!');
      }
    } catch (error) {
      console.error(error);
      this.showToast('Unable to share or copy link.');
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.storeManager = new StorePageManager();
});
