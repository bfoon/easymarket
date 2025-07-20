document.addEventListener('DOMContentLoaded', function () {
  // DOM elements
  const chatSidebar = document.getElementById('chatSidebar');
  const sidebarOverlay = document.getElementById('sidebarOverlay');
  const mobileToggle = document.getElementById('mobileToggle');
  const messagesContainer = document.getElementById('messagesContainer');
  const messageInput = document.getElementById('messageInput');
  const sendBtn = document.getElementById('sendBtn');
  const messageForm = document.getElementById('messageForm');
  const searchInput = document.getElementById('searchInput');
  const typingIndicator = document.getElementById('typingIndicator');
  const emojiBtn = document.getElementById('emojiBtn');

  // State management
  let typingTimer;
  let isTyping = false;
  let lastMessageTime = Date.now();

  // Initialize
  init();

  function init() {
    setupEventListeners();
    setupMessageInput();
    scrollToBottom();
    autoResizeTextarea();
    focusInput();

    // Check for new messages periodically
    setInterval(checkNewMessages, 5000);
  }

  function setupEventListeners() {
    // Mobile sidebar toggle
    mobileToggle?.addEventListener('click', toggleSidebar);
    sidebarOverlay?.addEventListener('click', closeSidebar);

    // Search functionality
    searchInput?.addEventListener('input', debounce(searchThreads, 300));

    // Message form
    messageForm?.addEventListener('submit', handleMessageSubmit);
    messageInput?.addEventListener('input', handleMessageInput);
    messageInput?.addEventListener('keydown', handleKeyDown);

    // Action buttons
    document.getElementById('callBtn')?.addEventListener('click', () => showNotification('Calling feature coming soon!', 'info'));
    document.getElementById('videoCallBtn')?.addEventListener('click', () => showNotification('Video calling feature coming soon!', 'info'));
    document.getElementById('emojiBtn')?.addEventListener('click', () => showNotification('Emoji picker coming soon!', 'info'));

    // Window resize
    window.addEventListener('resize', handleResize);

    // Keyboard shortcuts
    document.addEventListener('keydown', handleGlobalKeyboard);
  }

  function setupMessageInput() {
    if (!messageInput) return;

    // Enable/disable send button based on input
    const updateSendButton = () => {
      const hasContent = messageInput.value.trim().length > 0;
      sendBtn.disabled = !hasContent;
      sendBtn.style.opacity = hasContent ? '1' : '0.5';
    };

    messageInput.addEventListener('input', updateSendButton);
    updateSendButton(); // Initial state
  }

  function autoResizeTextarea() {
    if (!messageInput) return;

    messageInput.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
  }

  function toggleSidebar() {
    chatSidebar?.classList.add('open');
    sidebarOverlay?.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    chatSidebar?.classList.remove('open');
    sidebarOverlay?.classList.remove('active');
    document.body.style.overflow = '';
  }

  function scrollToBottom(smooth = true) {
    if (!messagesContainer) return;

    const scrollOptions = {
      top: messagesContainer.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto'
    };

    messagesContainer.scrollTo(scrollOptions);
  }

  function searchThreads() {
    const searchTerm = searchInput.value.toLowerCase();
    const threadItems = document.querySelectorAll('.thread-item[data-thread-id]');

    threadItems.forEach(item => {
      const name = item.querySelector('.thread-name')?.textContent.toLowerCase() || '';
      const preview = item.querySelector('.thread-preview')?.textContent.toLowerCase() || '';
      const isMatch = name.includes(searchTerm) || preview.includes(searchTerm);

      item.style.display = isMatch ? 'flex' : 'none';

      // Add search highlight effect
      if (searchTerm && isMatch) {
        item.style.background = 'rgba(255,255,255,0.15)';
      } else {
        item.style.background = '';
      }
    });

    // Show no results message
    const visibleThreads = document.querySelectorAll('.thread-item[data-thread-id][style*="flex"], .thread-item[data-thread-id]:not([style])');
    if (searchTerm && visibleThreads.length === 0) {
      showSearchNoResults();
    } else {
      hideSearchNoResults();
    }
  }

  function showSearchNoResults() {
    const existingMsg = document.querySelector('.search-no-results');
    if (existingMsg) return;

    const noResultsMsg = document.createElement('div');
    noResultsMsg.className = 'thread-item search-no-results';
    noResultsMsg.innerHTML = `
      <div style="text-align: center; width: 100%; color: rgba(255,255,255,0.7);">
        <i class="fas fa-search" style="font-size: 2rem; margin-bottom: 1rem; opacity: 0.5;"></i>
        <p>No conversations found</p>
        <small>Try a different search term</small>
      </div>
    `;
    document.querySelector('.threads-list').appendChild(noResultsMsg);
  }

  function hideSearchNoResults() {
    const existingMsg = document.querySelector('.search-no-results');
    if (existingMsg) {
      existingMsg.remove();
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (messageInput.value.trim()) {
        messageForm.dispatchEvent(new Event('submit', { cancelable: true }));
      }
    }
  }

  function handleMessageInput() {
    // Show typing indicator
    if (!isTyping) {
      isTyping = true;
      sendTypingIndicator(true);
    }

    // Clear previous timer
    clearTimeout(typingTimer);

    // Set new timer to stop typing indicator
    typingTimer = setTimeout(() => {
      isTyping = false;
      sendTypingIndicator(false);
    }, 2000);
  }

  function handleMessageSubmit(e) {
    e.preventDefault();

    const messageText = messageInput.value.trim();
    const recipientId = messageForm.querySelector('[name="recipient_id"]').value;
    const csrfToken = messageForm.querySelector('[name="csrfmiddlewaretoken"]').value;

    if (!messageText || !recipientId) return;

    const tempMessage = addMessageToUI(messageText, true, true);

    messageInput.value = '';
    messageInput.style.height = 'auto';
    sendBtn.disabled = true;
    messageForm.classList.add('loading');

    fetch(window.location.href, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: new URLSearchParams({
        message: messageText
      })
    })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        tempMessage.classList.remove('message-sending');
        tempMessage.dataset.messageId = data.message_id;
        updateThreadPreview(recipientId, messageText);
        showNotification('Message sent!', 'success');
        lastMessageTime = Date.now();
      } else {
        tempMessage.remove();
        showNotification(data.error || "Failed to send message", 'error');
      }
    })
    .catch(error => {
      console.error('Error sending message:', error);
      tempMessage.remove();
      showNotification("Network error. Try again.", 'error');
    })
    .finally(() => {
      messageForm.classList.remove('loading');
      messageInput.focus();
    });
  }

  function addMessageToUI(messageText, isSent, isTemp = false) {
    if (!messagesContainer) return null;

    const messageGroup = document.createElement('div');
    messageGroup.className = `message-group ${isTemp ? 'message-sending' : ''}`;

    const currentTime = new Date().toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });

    messageGroup.innerHTML = `
      <div class="message-bubble ${isSent ? 'sent' : 'received'}">
        <div class="message-content">${messageText.replace(/\n/g, '<br>')}</div>
        <div class="message-meta">
          <div class="message-time">
            <i class="fas fa-clock"></i> ${isTemp ? 'sending...' : currentTime}
          </div>
          ${isSent ? '<div class="message-status"><i class="fas fa-check" style="color: #6c757d;"></i></div>' : ''}
        </div>
      </div>
    `;

    messagesContainer.appendChild(messageGroup);
    scrollToBottom();

    return messageGroup;
  }

  function updateThreadPreview(recipientId, messageText) {
    const threadItem = document.querySelector(`[data-thread-id]`);
    if (threadItem) {
      const preview = threadItem.querySelector('.thread-preview');
      const time = threadItem.querySelector('.thread-time');

      if (preview) {
        preview.textContent = messageText.substring(0, 40) + (messageText.length > 40 ? '...' : '');
      }

      if (time) {
        time.textContent = 'now';
      }
    }
  }

  function sendTypingIndicator(isTyping) {
    // This would typically send a WebSocket message or AJAX request
    // to notify other users that someone is typing
    console.log('Typing indicator:', isTyping);
  }

  function checkNewMessages() {
    // Implement periodic checking for new messages
    // This could be replaced with WebSocket connections for real-time updates
    if (Date.now() - lastMessageTime > 30000) { // Check every 30 seconds if no recent activity
      // Make AJAX call to check for new messages
      console.log('Checking for new messages...');
    }
  }

  function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existing = document.querySelector('.notification-badge');
    if (existing) existing.remove();

    const notification = document.createElement('div');
    notification.className = `notification-badge ${type}`;
    notification.innerHTML = `
      <i class="fas fa-${getNotificationIcon(type)} me-2"></i>${message}
    `;

    document.body.appendChild(notification);

    // Show notification
    setTimeout(() => notification.classList.add('show'), 100);

    // Hide notification after 3 seconds
    setTimeout(() => {
      notification.classList.remove('show');
      setTimeout(() => notification.remove(), 300);
    }, 3000);
  }

  function getNotificationIcon(type) {
    const icons = {
      success: 'check-circle',
      error: 'exclamation-circle',
      warning: 'exclamation-triangle',
      info: 'info-circle'
    };
    return icons[type] || 'info-circle';
  }

  function handleResize() {
    if (window.innerWidth > 768) {
      closeSidebar();
    }
  }

  function handleGlobalKeyboard(e) {
    // Escape key closes sidebar
    if (e.key === 'Escape') {
      closeSidebar();
    }

    // Ctrl/Cmd + F focuses search
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      e.preventDefault();
      searchInput?.focus();
    }
  }

  function focusInput() {
    // Focus message input on desktop
    if (window.innerWidth > 768 && messageInput) {
      messageInput.focus();
    }
  }

  // Utility function for debouncing
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

  // Initialize emoji support (placeholder)
  function initializeEmojis() {
    // This would initialize an emoji picker
    // For now, it's just a placeholder
    console.log('Emoji support ready');
  }

  // Sound notifications (optional)
  function playNotificationSound() {
    try {
      const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+L10GYdCEOX2+/CeiMFMIzN8NWJNQYXY7zs5Z1NEQ1Hpd/js2ECDi5PBIvQ8tOH+Zzb7Nq');
      audio.volume = 0.1;
      audio.play().catch(() => {});
    } catch (e) {
      // Ignore audio errors
    }
  }
});document.addEventListener('DOMContentLoaded', function () {
  // DOM elements
  const chatSidebar = document.getElementById('chatSidebar');
  const sidebarOverlay = document.getElementById('sidebarOverlay');
  const mobileToggle = document.getElementById('mobileToggle');
  const messagesContainer = document.getElementById('messagesContainer');
  const messageInput = document.getElementById('messageInput');
  const sendBtn = document.getElementById('sendBtn');
  const messageForm = document.getElementById('messageForm');
  const searchInput = document.getElementById('searchInput');
  const typingIndicator = document.getElementById('typingIndicator');
  const emojiBtn = document.getElementById('emojiBtn');

  // State management
  let typingTimer;
  let isTyping = false;
  let lastMessageTime = Date.now();

  // Initialize
  init();

  function init() {
    setupEventListeners();
    setupMessageInput();
    scrollToBottom();
    autoResizeTextarea();
    focusInput();

    // Check for new messages periodically
    setInterval(checkNewMessages, 5000);
  }

  function setupEventListeners() {
    // Mobile sidebar toggle
    mobileToggle?.addEventListener('click', toggleSidebar);
    sidebarOverlay?.addEventListener('click', closeSidebar);

    // Search functionality
    searchInput?.addEventListener('input', debounce(searchThreads, 300));

    // Message form
    messageForm?.addEventListener('submit', handleMessageSubmit);
    messageInput?.addEventListener('input', handleMessageInput);
    messageInput?.addEventListener('keydown', handleKeyDown);

    // Action buttons
    document.getElementById('callBtn')?.addEventListener('click', () => showNotification('Calling feature coming soon!', 'info'));
    document.getElementById('videoCallBtn')?.addEventListener('click', () => showNotification('Video calling feature coming soon!', 'info'));
    document.getElementById('emojiBtn')?.addEventListener('click', () => showNotification('Emoji picker coming soon!', 'info'));

    // Window resize
    window.addEventListener('resize', handleResize);

    // Keyboard shortcuts
    document.addEventListener('keydown', handleGlobalKeyboard);
  }

  function setupMessageInput() {
    if (!messageInput) return;

    // Enable/disable send button based on input
    const updateSendButton = () => {
      const hasContent = messageInput.value.trim().length > 0;
      sendBtn.disabled = !hasContent;
      sendBtn.style.opacity = hasContent ? '1' : '0.5';
    };

    messageInput.addEventListener('input', updateSendButton);
    updateSendButton(); // Initial state
  }

  function autoResizeTextarea() {
    if (!messageInput) return;

    messageInput.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
  }

  function toggleSidebar() {
    chatSidebar?.classList.add('open');
    sidebarOverlay?.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    chatSidebar?.classList.remove('open');
    sidebarOverlay?.classList.remove('active');
    document.body.style.overflow = '';
  }

  function scrollToBottom(smooth = true) {
    if (!messagesContainer) return;

    const scrollOptions = {
      top: messagesContainer.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto'
    };

    messagesContainer.scrollTo(scrollOptions);
  }

  function searchThreads() {
    const searchTerm = searchInput.value.toLowerCase();
    const threadItems = document.querySelectorAll('.thread-item[data-thread-id]');

    threadItems.forEach(item => {
      const name = item.querySelector('.thread-name')?.textContent.toLowerCase() || '';
      const preview = item.querySelector('.thread-preview')?.textContent.toLowerCase() || '';
      const isMatch = name.includes(searchTerm) || preview.includes(searchTerm);

      item.style.display = isMatch ? 'flex' : 'none';

      // Add search highlight effect
      if (searchTerm && isMatch) {
        item.style.background = 'rgba(255,255,255,0.15)';
      } else {
        item.style.background = '';
      }
    });

    // Show no results message
    const visibleThreads = document.querySelectorAll('.thread-item[data-thread-id][style*="flex"], .thread-item[data-thread-id]:not([style])');
    if (searchTerm && visibleThreads.length === 0) {
      showSearchNoResults();
    } else {
      hideSearchNoResults();
    }
  }

  function showSearchNoResults() {
    const existingMsg = document.querySelector('.search-no-results');
    if (existingMsg) return;

    const noResultsMsg = document.createElement('div');
    noResultsMsg.className = 'thread-item search-no-results';
    noResultsMsg.innerHTML = `
      <div style="text-align: center; width: 100%; color: rgba(255,255,255,0.7);">
        <i class="fas fa-search" style="font-size: 2rem; margin-bottom: 1rem; opacity: 0.5;"></i>
        <p>No conversations found</p>
        <small>Try a different search term</small>
      </div>
    `;
    document.querySelector('.threads-list').appendChild(noResultsMsg);
  }

  function hideSearchNoResults() {
    const existingMsg = document.querySelector('.search-no-results');
    if (existingMsg) {
      existingMsg.remove();
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (messageInput.value.trim()) {
        messageForm.dispatchEvent(new Event('submit', { cancelable: true }));
      }
    }
  }

  function handleMessageInput() {
    // Show typing indicator
    if (!isTyping) {
      isTyping = true;
      sendTypingIndicator(true);
    }

    // Clear previous timer
    clearTimeout(typingTimer);

    // Set new timer to stop typing indicator
    typingTimer = setTimeout(() => {
      isTyping = false;
      sendTypingIndicator(false);
    }, 2000);
  }

  function handleMessageSubmit(e) {
    e.preventDefault();

    const messageText = messageInput.value.trim();
    const recipientId = messageForm.querySelector('[name="recipient_id"]').value;
    const csrfToken = messageForm.querySelector('[name="csrfmiddlewaretoken"]').value;

    if (!messageText || !recipientId) return;

    const tempMessage = addMessageToUI(messageText, true, true);

    messageInput.value = '';
    messageInput.style.height = 'auto';
    sendBtn.disabled = true;
    messageForm.classList.add('loading');

    fetch(window.location.href, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: new URLSearchParams({
        message: messageText
      })
    })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        tempMessage.classList.remove('message-sending');
        tempMessage.dataset.messageId = data.message_id;
        updateThreadPreview(recipientId, messageText);
        showNotification('Message sent!', 'success');
        lastMessageTime = Date.now();
      } else {
        tempMessage.remove();
        showNotification(data.error || "Failed to send message", 'error');
      }
    })
    .catch(error => {
      console.error('Error sending message:', error);
      tempMessage.remove();
      showNotification("Network error. Try again.", 'error');
    })
    .finally(() => {
      messageForm.classList.remove('loading');
      messageInput.focus();
    });
  }

  function addMessageToUI(messageText, isSent, isTemp = false) {
    if (!messagesContainer) return null;

    const messageGroup = document.createElement('div');
    messageGroup.className = `message-group ${isTemp ? 'message-sending' : ''}`;

    const currentTime = new Date().toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });

    messageGroup.innerHTML = `
      <div class="message-bubble ${isSent ? 'sent' : 'received'}">
        <div class="message-content">${messageText.replace(/\n/g, '<br>')}</div>
        <div class="message-meta">
          <div class="message-time">
            <i class="fas fa-clock"></i> ${isTemp ? 'sending...' : currentTime}
          </div>
          ${isSent ? '<div class="message-status"><i class="fas fa-check" style="color: #6c757d;"></i></div>' : ''}
        </div>
      </div>
    `;

    messagesContainer.appendChild(messageGroup);
    scrollToBottom();

    return messageGroup;
  }

  function updateThreadPreview(recipientId, messageText) {
    const threadItem = document.querySelector(`[data-thread-id]`);
    if (threadItem) {
      const preview = threadItem.querySelector('.thread-preview');
      const time = threadItem.querySelector('.thread-time');

      if (preview) {
        preview.textContent = messageText.substring(0, 40) + (messageText.length > 40 ? '...' : '');
      }

      if (time) {
        time.textContent = 'now';
      }
    }
  }

  function sendTypingIndicator(isTyping) {
    // This would typically send a WebSocket message or AJAX request
    // to notify other users that someone is typing
    console.log('Typing indicator:', isTyping);
  }

  function checkNewMessages() {
    // Implement periodic checking for new messages
    // This could be replaced with WebSocket connections for real-time updates
    if (Date.now() - lastMessageTime > 30000) { // Check every 30 seconds if no recent activity
      // Make AJAX call to check for new messages
      console.log('Checking for new messages...');
    }
  }

  function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existing = document.querySelector('.notification-badge');
    if (existing) existing.remove();

    const notification = document.createElement('div');
    notification.className = `notification-badge ${type}`;
    notification.innerHTML = `
      <i class="fas fa-${getNotificationIcon(type)} me-2"></i>${message}
    `;

    document.body.appendChild(notification);

    // Show notification
    setTimeout(() => notification.classList.add('show'), 100);

    // Hide notification after 3 seconds
    setTimeout(() => {
      notification.classList.remove('show');
      setTimeout(() => notification.remove(), 300);
    }, 3000);
  }

  function getNotificationIcon(type) {
    const icons = {
      success: 'check-circle',
      error: 'exclamation-circle',
      warning: 'exclamation-triangle',
      info: 'info-circle'
    };
    return icons[type] || 'info-circle';
  }

  function handleResize() {
    if (window.innerWidth > 768) {
      closeSidebar();
    }
  }

  function handleGlobalKeyboard(e) {
    // Escape key closes sidebar
    if (e.key === 'Escape') {
      closeSidebar();
    }

    // Ctrl/Cmd + F focuses search
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      e.preventDefault();
      searchInput?.focus();
    }
  }

  function focusInput() {
    // Focus message input on desktop
    if (window.innerWidth > 768 && messageInput) {
      messageInput.focus();
    }
  }

  // Utility function for debouncing
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

  // Initialize emoji support (placeholder)
  function initializeEmojis() {
    // This would initialize an emoji picker
    // For now, it's just a placeholder
    console.log('Emoji support ready');
  }

  // Sound notifications (optional)
  function playNotificationSound() {
    try {
      const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+L10GYdCEOX2+/CeiMFMIzN8NWJNQYXY7zs5Z1NEQ1Hpd/js2ECDi5PBIvQ8tOH+Zzb7Nq');
      audio.volume = 0.1;
      audio.play().catch(() => {});
    } catch (e) {
      // Ignore audio errors
    }
  }
});