document.addEventListener('DOMContentLoaded', function() {
  const chatForm = document.getElementById('chatForm');
  const chatMessages = document.getElementById('chatMessages');
  const chatMessage = document.getElementById('chatMessage');
  const sendMessageBtn = document.getElementById('sendMessageBtn');
  const imageInput = document.getElementById('chatImage');               // NEW
  const imagePreview = document.getElementById('imagePreview');          // optional (if you added preview block)
  const imagePreviewThumb = document.getElementById('imagePreviewThumb');// optional
  const imagePreviewName = document.getElementById('imagePreviewName');  // optional
  const removeImageBtn = document.getElementById('removeImageBtn');      // optional

  const sendUrl = chatForm.dataset.sendUrl;
  const fetchUrl = chatMessages.dataset.fetchUrl;

  function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // Basic HTML escaper to prevent XSS when inserting text
  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Show a just-sent message bubble (supports text and/or image)
  function appendOwnBubble({ content, image_url, timestamp }) {
    const safeContent = escapeHtml(content || '');
    const hasText = !!safeContent;
    const hasImage = !!image_url;

    const messageHtml = `
      <div class="message mb-3 sent">
        <div class="message-content">
          <div class="message-bubble bg-primary text-white ms-auto p-3 rounded" style="max-width: 80%;">
            ${hasText ? `<p class="mb-2">${safeContent.replace(/\n/g, '<br>')}</p>` : ''}
            ${hasImage ? `
              <a href="${image_url}" target="_blank" rel="noopener">
                <img src="${image_url}" alt="attachment" class="img-fluid rounded" style="max-height:240px;">
              </a>` : ''
            }
            <small class="text-white-50">${timestamp || 'Just now'}</small>
          </div>
          <div class="message-sender mt-1 text-end">
            <small class="text-muted">You</small>
          </div>
        </div>
      </div>
    `;
    const emptyState = chatMessages.querySelector('.text-center.text-muted.py-5');
    if (emptyState) emptyState.remove();
    chatMessages.insertAdjacentHTML('beforeend', messageHtml);
    scrollToBottom();
  }

  // Render a message from polling (supports text and/or image)
  function appendAnyBubble(msg) {
    const isSelf = !!msg.is_self;
    const bubbleClass = isSelf ? 'bg-primary text-white ms-auto' : 'bg-light';
    const tsClass = isSelf ? 'text-white-50' : 'text-muted';
    const safeContent = escapeHtml(msg.content || '');
    const hasText = !!safeContent;
    const hasImage = !!msg.image_url;

    const msgDiv = document.createElement('div');
    msgDiv.classList.add('message', 'mb-3', isSelf ? 'sent' : 'received');
    msgDiv.innerHTML = `
      <div class="message-content">
        <div class="message-bubble ${bubbleClass} p-3 rounded" style="max-width: 80%;">
          ${hasText ? `<p class="mb-2">${safeContent.replace(/\n/g, '<br>')}</p>` : ''}
          ${hasImage ? `
            <a href="${msg.image_url}" target="_blank" rel="noopener">
              <img src="${msg.image_url}" alt="attachment" class="img-fluid rounded" style="max-height:240px;">
            </a>` : ''
          }
          <small class="${tsClass}">${msg.timestamp || ''}</small>
        </div>
        <div class="message-sender mt-1 ${isSelf ? 'text-end' : ''}">
          <small class="text-muted">${isSelf ? 'You' : (escapeHtml(msg.sender_name) || '')}</small>
        </div>
      </div>`;
    chatMessages.appendChild(msgDiv);
    scrollToBottom();
  }

  // ---- Image preview (optional UI) ----
  if (imageInput) {
    imageInput.addEventListener('change', () => {
      const file = imageInput.files && imageInput.files[0];
      if (!file) { if (imagePreview) imagePreview.classList.add('d-none'); return; }

      // Client-side checks
      if (!file.type.startsWith('image/')) {
        alert('Please select a valid image.');
        imageInput.value = '';
        if (imagePreview) imagePreview.classList.add('d-none');
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        alert('Image too large (max 5MB).');
        imageInput.value = '';
        if (imagePreview) imagePreview.classList.add('d-none');
        return;
      }

      if (imagePreview && imagePreviewThumb && imagePreviewName) {
        const url = URL.createObjectURL(file);
        imagePreviewThumb.src = url;
        imagePreviewName.textContent = file.name;
        imagePreview.classList.remove('d-none');
      }
    });
  }
  if (removeImageBtn) {
    removeImageBtn.addEventListener('click', () => {
      if (imageInput) imageInput.value = '';
      if (imagePreview) imagePreview.classList.add('d-none');
    });
  }

  // Initialize scroll
  scrollToBottom();

  // Submit handler: allow sending text OR image OR both
  chatForm.addEventListener('submit', function(e) {
    e.preventDefault();
    const messageText = (chatMessage?.value || '').trim();
    const hasImage = imageInput && imageInput.files && imageInput.files[0];

    if (!messageText && !hasImage) return; // must have something

    sendMessageBtn.disabled = true;
    sendMessageBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    const formData = new FormData(chatForm); // includes text, order_id, csrf, and image (if chosen)

    fetch(sendUrl, {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': formData.get('csrfmiddlewaretoken')
      }
    })
    .then(async res => {
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) throw new Error(data.error || data.message || 'Failed to send');

      // Server returns: id, content, image_url, sender, created_at, is_sender
      appendOwnBubble({
        content: data.message.content || '',
        image_url: data.message.image_url || '',
        timestamp: data.message.created_at || 'Just now'
      });

      // Clear inputs
      if (chatMessage) {
        chatMessage.value = '';
        chatMessage.dispatchEvent(new Event('input')); // keep auto-resize/counter in sync
      }
      if (imageInput) imageInput.value = '';
      if (imagePreview) imagePreview.classList.add('d-none');
    })
    .catch(err => {
      console.error('Error:', err);
      alert('Failed to send message. Please try again.');
    })
    .finally(() => {
      sendMessageBtn.disabled = false;
      sendMessageBtn.innerHTML = '<i class="fas fa-paper-plane"></i><span class="d-none d-sm-inline ms-1">Send</span>';
    });
  });

  // Enter to send (Shift+Enter = newline)
  if (chatMessage) {
    chatMessage.addEventListener('keypress', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event('submit'));
      }
    });

    // Auto-resize
    chatMessage.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
  }

  // Auto refresh chat
  const lastMessageIds = new Set();
  function refreshChatMessages() {
    fetch(fetchUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(res => res.json())
      .then(data => {
        if (!data.success || !Array.isArray(data.messages)) return;

        data.messages.forEach(msg => {
          if (!lastMessageIds.has(msg.id)) {
            appendAnyBubble(msg);       // now shows images if msg.image_url present
            lastMessageIds.add(msg.id);
          }
        });
      })
      .catch(() => {});
  }

  refreshChatMessages();
  setInterval(refreshChatMessages, 5000);
});
