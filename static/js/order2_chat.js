document.addEventListener('DOMContentLoaded', function() {
    const chatForm = document.getElementById('chatForm');
    const chatMessages = document.getElementById('chatMessages');
    const chatMessage = document.getElementById('chatMessage');
    const sendMessageBtn = document.getElementById('sendMessageBtn');

    const sendUrl = chatForm.dataset.sendUrl;
    const fetchUrl = chatMessages.dataset.fetchUrl;

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Initialize scroll
    scrollToBottom();

    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const messageText = chatMessage.value.trim();
        if (!messageText) return;

        sendMessageBtn.disabled = true;
        sendMessageBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        const formData = new FormData(chatForm);

        fetch(sendUrl, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': formData.get('csrfmiddlewaretoken')
            }
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const messageHtml = `
                    <div class="message mb-3 sent">
                        <div class="message-content">
                            <div class="message-bubble bg-primary text-white ms-auto p-3 rounded">
                                <p class="mb-1">${messageText}</p>
                                <small class="text-white-50">Just now</small>
                            </div>
                            <div class="message-sender mt-1 text-end">
                                <small class="text-muted">You</small>
                            </div>
                        </div>
                    </div>`;
                const emptyState = chatMessages.querySelector('.text-center.text-muted.py-5');
                if (emptyState) emptyState.remove();
                chatMessages.insertAdjacentHTML('beforeend', messageHtml);
                chatMessage.value = '';
                scrollToBottom();
            } else {
                alert('Failed to send message. Please try again.');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('An error occurred. Please try again.');
        })
        .finally(() => {
            sendMessageBtn.disabled = false;
            sendMessageBtn.innerHTML = '<i class="fas fa-paper-plane"></i><span class="d-none d-sm-inline ms-1">Send</span>';
        });
    });

    chatMessage.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    chatMessage.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });

    // Auto refresh chat
    const lastMessageIds = new Set();
    function refreshChatMessages() {
        fetch(fetchUrl, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                data.messages.forEach(msg => {
                    if (!lastMessageIds.has(msg.id)) {
                        const msgDiv = document.createElement('div');
                        msgDiv.classList.add('message', 'mb-3');
                        msgDiv.classList.add(msg.is_self ? 'sent' : 'received');
                        msgDiv.innerHTML = `
                            <div class="message-content">
                                <div class="message-bubble ${msg.is_self ? 'bg-primary text-white ms-auto' : 'bg-light'} p-3 rounded">
                                    <p class="mb-1">${msg.content}</p>
                                    <small class="${msg.is_self ? 'text-white-50' : 'text-muted'}">${msg.timestamp}</small>
                                </div>
                                <div class="message-sender mt-1 ${msg.is_self ? 'text-end' : ''}">
                                    <small class="text-muted">${msg.is_self ? 'You' : msg.sender_name}</small>
                                </div>
                            </div>`;
                        chatMessages.appendChild(msgDiv);
                        lastMessageIds.add(msg.id);
                        scrollToBottom();
                    }
                });
            }
        });
    }

    refreshChatMessages();
    setInterval(refreshChatMessages, 5000);
});
