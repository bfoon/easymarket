/**
 * Social Cart Management Module
 * Handles collaborative cart creation, invitations, member management, and split modes
 * 
 * @requires CSRF token (from getCSRFToken() or Django template)
 * @requires bootstrap (for toast notifications)
 */

(function() {
    'use strict';

    // Configuration
    const STORAGE_KEYS = {
        SOCIAL_ID: 'em_social_id',
        INVITE_LINK: 'em_social_invite'
    };

    // State
    let socialId = null;
    let socialInviteLink = '';
    let csrfToken = '';

    // DOM Elements
    const elements = {
        // Buttons
        createBtn: null,
        sendInviteBtn: null,
        copyInviteBtn: null,
        leaveBtn: null,
        
        // Inputs
        inviteEmail: null,
        invitePhone: null,
        inviteLinkEl: null,
        socialIdInput: null,
        
        // Containers
        actionsWrap: null,
        ctaCard: null,
        serverCard: null,
        
        // Split mode elements
        btnSplitItems: null,
        btnSplitPercent: null,
        btnSplitSingle: null,
        percentBox: null,
        payerBox: null,
        btnApplyPercent: null,
        btnApplySingle: null,
        singlePayerSel: null,
        pctInputs: null,
        pctTotalHint: null,
        currentSplitEl: null
    };

    /**
     * Initialize the social cart module
     */
    function init() {
        // Get CSRF token
        csrfToken = getCSRFToken();
        
        if (!csrfToken) {
            console.error('CSRF token not found - social cart operations will fail');
        }

        // Initialize DOM elements
        initializeElements();

        // Initialize state
        initializeState();

        // Attach event listeners
        attachEventListeners();

        console.log('Social cart module initialized');
    }

    /**
     * Get all DOM elements
     */
    function initializeElements() {
        // Buttons
        elements.createBtn = document.getElementById('createSocialCartBtn');
        elements.sendInviteBtn = document.getElementById('sendInviteBtn');
        elements.copyInviteBtn = document.getElementById('copyInviteBtn');
        elements.leaveBtn = document.getElementById('leaveCartBtn');

        // Inputs
        elements.inviteEmail = document.getElementById('inviteEmail');
        elements.invitePhone = document.getElementById('invitePhone');
        elements.inviteLinkEl = document.getElementById('socialInviteLink');
        elements.socialIdInput = document.getElementById('socialId');

        // Containers
        elements.actionsWrap = document.getElementById('socialCartActions');
        elements.ctaCard = document.getElementById('socialCtaCard');
        elements.serverCard = document.getElementById('socialServerCard');

        // Split mode elements
        elements.btnSplitItems = document.getElementById('btnSplitItems');
        elements.btnSplitPercent = document.getElementById('btnSplitPercent');
        elements.btnSplitSingle = document.getElementById('btnSplitSingle');
        elements.percentBox = document.getElementById('percentBox');
        elements.payerBox = document.getElementById('payerBox');
        elements.btnApplyPercent = document.getElementById('btnApplyPercent');
        elements.btnApplySingle = document.getElementById('btnApplySingle');
        elements.singlePayerSel = document.getElementById('singlePayer');
        elements.pctInputs = document.querySelectorAll('.split-pct');
        elements.pctTotalHint = document.getElementById('pctTotalHint');
        elements.currentSplitEl = document.getElementById('currentSplitMode');
    }

    /**
     * Initialize state from server and localStorage
     */
    function initializeState() {
        // Get social ID from server (Django template) or localStorage
        const serverSocialId = elements.socialIdInput?.value || null;
        socialId = serverSocialId || localStorage.getItem(STORAGE_KEYS.SOCIAL_ID) || null;
        socialInviteLink = localStorage.getItem(STORAGE_KEYS.INVITE_LINK) || '';

        // If no server social but we have stored social, keep actions visible
        if (!serverSocialId && socialId) {
            showSocialActions();
            fetchAndUpdateInviteLink();
        }

        // If server provided a social, sync storage
        if (serverSocialId) {
            localStorage.setItem(STORAGE_KEYS.SOCIAL_ID, serverSocialId);
            fetchAndUpdateInviteLink();
        } else if (socialInviteLink && elements.inviteLinkEl) {
            elements.inviteLinkEl.value = socialInviteLink;
        }
    }

    /**
     * Fetch and update invite link from server
     */
    function fetchAndUpdateInviteLink() {
        const shareUrl = window.CART_SHARE_URL || '/cart/share/';
        
        fetch(shareUrl)
            .then(response => response.json())
            .then(data => {
                if (data.share_url) {
                    socialInviteLink = data.share_url;
                    localStorage.setItem(STORAGE_KEYS.INVITE_LINK, socialInviteLink);
                    
                    if (elements.inviteLinkEl) {
                        elements.inviteLinkEl.value = socialInviteLink;
                    }
                }
            })
            .catch(error => {
                console.warn('Failed to fetch share URL:', error);
            });
    }

    /**
     * Show social cart actions UI
     */
    function showSocialActions() {
        if (elements.actionsWrap) {
            elements.actionsWrap.style.display = 'block';
        }
        if (elements.ctaCard) {
            elements.ctaCard.style.display = 'none';
        }
    }

    /**
     * Hide social cart actions UI
     */
    function hideSocialActions() {
        if (elements.actionsWrap) {
            elements.actionsWrap.style.display = 'none';
        }
        if (elements.ctaCard) {
            elements.ctaCard.style.display = 'block';
        }
    }

    /**
     * Attach all event listeners
     */
    function attachEventListeners() {
        // Create social cart
        if (elements.createBtn) {
            elements.createBtn.addEventListener('click', handleCreateSocialCart);
        }

        // Send invite
        if (elements.sendInviteBtn) {
            elements.sendInviteBtn.addEventListener('click', handleSendInvite);
        }

        // Copy invite link
        if (elements.copyInviteBtn) {
            elements.copyInviteBtn.addEventListener('click', handleCopyInviteLink);
        }

        // Leave cart
        if (elements.leaveBtn) {
            elements.leaveBtn.addEventListener('click', handleLeaveCart);
        }

        // Remove member buttons
        document.querySelectorAll('.js-remove-member').forEach(btn => {
            btn.addEventListener('click', handleRemoveMember);
        });

        // Split mode buttons
        attachSplitModeListeners();
    }

    /**
     * Attach split mode event listeners
     */
    function attachSplitModeListeners() {
        if (elements.btnSplitItems) {
            elements.btnSplitItems.addEventListener('click', () => handleSplitByItems());
        }

        if (elements.btnSplitPercent) {
            elements.btnSplitPercent.addEventListener('click', showPercentBox);
        }

        if (elements.btnSplitSingle) {
            elements.btnSplitSingle.addEventListener('click', showPayerBox);
        }

        if (elements.btnApplyPercent) {
            elements.btnApplyPercent.addEventListener('click', handleApplyPercent);
        }

        if (elements.btnApplySingle) {
            elements.btnApplySingle.addEventListener('click', handleApplySinglePayer);
        }

        // Live percentage total calculation
        if (elements.pctInputs) {
            elements.pctInputs.forEach(input => {
                input.addEventListener('input', updatePercentageTotal);
            });
        }
    }

    // ========================================================================
    // Event Handlers
    // ========================================================================

    /**
     * Handle create social cart
     */
    async function handleCreateSocialCart() {
        const btn = elements.createBtn;
        const originalHTML = btn.innerHTML;
        
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating...';

        try {
            const createUrl = window.CREATE_SOCIAL_CART_URL || '/cart/create-social/';
            
            const response = await fetch(createUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                }
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'Failed to create social cart');
            }

            // Store social ID from response
            socialId = data.social_id;
            localStorage.setItem(STORAGE_KEYS.SOCIAL_ID, socialId);

            // Fetch invite link
            await fetchAndUpdateInviteLink();

            // Show actions UI with animation
            if (elements.actionsWrap) {
                elements.actionsWrap.style.display = 'block';
                elements.actionsWrap.style.opacity = '0';
                elements.actionsWrap.style.transition = 'opacity 0.3s ease';
                void elements.actionsWrap.offsetWidth; // Force reflow
                elements.actionsWrap.style.opacity = '1';
            }

            if (elements.ctaCard) {
                elements.ctaCard.style.display = 'none';
            }

            showToast('Social cart created! Share the link with friends.', 'success');

        } catch (error) {
            console.error('Error creating social cart:', error);
            showToast(error.message || 'Error creating social cart', 'danger');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    }

    /**
     * Handle send invite
     */
    async function handleSendInvite() {
        if (!socialId) {
            showToast('No active social cart', 'warning');
            return;
        }

        const email = (elements.inviteEmail?.value || '').trim();
        const phone = (elements.invitePhone?.value || '').trim();

        if (!email && !phone) {
            showToast('Enter an email or phone number', 'warning');
            return;
        }

        const btn = elements.sendInviteBtn;
        const originalHTML = btn.innerHTML;
        
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

        try {
            const inviteUrl = window.SEND_INVITE_URL || '/cart/send-invite/';
            
            const response = await fetch(inviteUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': csrfToken
                },
                body: new URLSearchParams({
                    email: email,
                    phone: phone,
                    social_id: socialId
                })
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'Failed to send invite');
            }

            // Update invite link if provided
            if (data.invite_link) {
                socialInviteLink = data.invite_link;
                localStorage.setItem(STORAGE_KEYS.INVITE_LINK, socialInviteLink);
                
                if (elements.inviteLinkEl) {
                    elements.inviteLinkEl.value = socialInviteLink;
                }
            }

            // Clear inputs
            if (elements.inviteEmail) elements.inviteEmail.value = '';
            if (elements.invitePhone) elements.invitePhone.value = '';

            showToast('Invitation sent successfully!', 'success');

        } catch (error) {
            console.error('Error sending invite:', error);
            showToast(error.message || 'Error sending invite', 'danger');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    }

    /**
     * Handle copy invite link
     */
    function handleCopyInviteLink() {
        const linkToCopy = elements.inviteLinkEl?.value || localStorage.getItem(STORAGE_KEYS.INVITE_LINK);

        if (!linkToCopy) {
            showToast('No invite link available', 'warning');
            return;
        }

        // Try modern clipboard API
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(linkToCopy)
                .then(() => {
                    showToast('Invite link copied!', 'success');
                })
                .catch(() => {
                    fallbackCopyText(linkToCopy);
                });
        } else {
            fallbackCopyText(linkToCopy);
        }
    }

    /**
     * Handle leave cart
     */
    async function handleLeaveCart() {
        if (!socialId) {
            showToast('No active social cart', 'warning');
            return;
        }

        if (!confirm('Leave this collaborative cart?')) {
            return;
        }

        const btn = elements.leaveBtn;
        const originalHTML = btn.innerHTML;
        
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Leaving...';

        try {
            const leaveUrl = window.LEAVE_CART_URL || '/cart/leave/';
            
            const response = await fetch(leaveUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': csrfToken
                },
                body: new URLSearchParams({
                    social_id: socialId
                })
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'Failed to leave cart');
            }

            // Clear storage
            localStorage.removeItem(STORAGE_KEYS.SOCIAL_ID);
            localStorage.removeItem(STORAGE_KEYS.INVITE_LINK);

            // Update UI
            hideSocialActions();
            
            if (elements.serverCard) {
                elements.serverCard.style.display = 'none';
            }

            showToast('You have left the cart', 'info');

        } catch (error) {
            console.error('Error leaving cart:', error);
            showToast(error.message || 'Error leaving cart', 'danger');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    }

    /**
     * Handle remove member
     */
    async function handleRemoveMember(event) {
        const btn = event.currentTarget;
        const url = btn.dataset.removeUrl;

        if (!url) {
            showToast('Invalid remove URL', 'danger');
            return;
        }

        if (!confirm('Remove this member from the social cart?')) {
            return;
        }

        const originalHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                }
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'Failed to remove member');
            }

            showToast('Member removed successfully', 'success');

            // Reload page after short delay
            setTimeout(() => {
                window.location.reload();
            }, 600);

        } catch (error) {
            console.error('Error removing member:', error);
            showToast(error.message || 'Error removing member', 'danger');
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    }

    // ========================================================================
    // Split Mode Handlers
    // ========================================================================

    /**
     * Handle split by items
     */
    async function handleSplitByItems() {
        hideAllSplitBoxes();

        try {
            const data = await postSplitMode({ mode: 'by_items' });

            if (data.success) {
                if (elements.currentSplitEl) {
                    elements.currentSplitEl.textContent = 'By Items';
                }
                showToast('Split set: Each pays their items', 'success');
            } else {
                throw new Error(data.message || 'Failed to set split');
            }
        } catch (error) {
            console.error('Error setting split mode:', error);
            showToast('Error setting split', 'danger');
        }
    }

    /**
     * Show percentage split box
     */
    function showPercentBox() {
        hideAllSplitBoxes();
        
        if (elements.percentBox) {
            elements.percentBox.style.display = 'block';
        }
    }

    /**
     * Show single payer box
     */
    function showPayerBox() {
        hideAllSplitBoxes();
        
        if (elements.payerBox) {
            elements.payerBox.style.display = 'block';
        }
    }

    /**
     * Hide all split mode boxes
     */
    function hideAllSplitBoxes() {
        if (elements.percentBox) {
            elements.percentBox.style.display = 'none';
        }
        if (elements.payerBox) {
            elements.payerBox.style.display = 'none';
        }
    }

    /**
     * Update percentage total display
     */
    function updatePercentageTotal() {
        if (!elements.pctInputs || !elements.pctTotalHint) {
            return;
        }

        const total = Array.from(elements.pctInputs).reduce((sum, input) => {
            return sum + (parseFloat(input.value || '0') || 0);
        }, 0);

        elements.pctTotalHint.textContent = `Total: ${total.toFixed(2)}%`;
        
        if (total.toFixed(2) === '100.00') {
            elements.pctTotalHint.className = 'text-success small';
        } else {
            elements.pctTotalHint.className = 'text-danger small';
        }
    }

    /**
     * Handle apply percentage split
     */
    async function handleApplyPercent() {
        if (!elements.pctInputs) {
            return;
        }

        const allocations = {};
        let total = 0;

        elements.pctInputs.forEach(input => {
            const value = parseFloat(input.value || '0') || 0;
            total += value;
            allocations[input.dataset.memberId] = value;
        });

        if (total.toFixed(2) !== '100.00') {
            showToast('Percentages must total 100%', 'warning');
            return;
        }

        try {
            const data = await postSplitMode({
                mode: 'by_percent',
                allocations: JSON.stringify(allocations)
            });

            if (data.success) {
                if (elements.currentSplitEl) {
                    elements.currentSplitEl.textContent = 'Percent';
                }
                showToast('Split set: Pay by percentage', 'success');
            } else {
                throw new Error(data.message || 'Failed to set split');
            }
        } catch (error) {
            console.error('Error setting percentage split:', error);
            showToast('Error setting split', 'danger');
        }
    }

    /**
     * Handle apply single payer
     */
    async function handleApplySinglePayer() {
        const payerId = elements.singlePayerSel?.value;

        if (!payerId) {
            showToast('Select a payer', 'warning');
            return;
        }

        try {
            const data = await postSplitMode({
                mode: 'single_payer',
                payer_member_id: payerId
            });

            if (data.success) {
                if (elements.currentSplitEl) {
                    elements.currentSplitEl.textContent = 'Single Payer';
                }
                showToast('Split set: One person pays full', 'success');
            } else {
                throw new Error(data.message || 'Failed to set split');
            }
        } catch (error) {
            console.error('Error setting single payer:', error);
            showToast('Error setting split', 'danger');
        }
    }

    /**
     * Post split mode to server
     * @param {Object} payload - Split mode data
     * @returns {Promise<Object>} Response data
     */
    async function postSplitMode(payload) {
        const splitUrl = window.SET_SPLIT_MODE_URL || '/cart/set-split-mode/';
        
        const response = await fetch(splitUrl, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: new URLSearchParams(payload)
        });

        return response.json();
    }

    // ========================================================================
    // Utility Functions
    // ========================================================================

    /**
     * Get CSRF token from cookies or DOM
     * @returns {string} CSRF token
     */
    function getCSRFToken() {
        // Try window.getCSRFToken if available
        if (window.getCSRFToken && typeof window.getCSRFToken === 'function') {
            return window.getCSRFToken();
        }

        // Try to get from cookie
        let token = getCookie('csrftoken');
        
        // Fallback to hidden input
        if (!token) {
            const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
            if (tokenInput) {
                token = tokenInput.value;
            }
        }
        
        return token || '';
    }

    /**
     * Get cookie value by name
     * @param {string} name - Cookie name
     * @returns {string|null} Cookie value
     */
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    /**
     * Fallback method for copying text
     * @param {string} text - Text to copy
     */
    function fallbackCopyText(text) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        
        document.body.appendChild(textarea);
        textarea.select();

        try {
            document.execCommand('copy');
            showToast('Invite link copied!', 'success');
        } catch (err) {
            console.error('Copy failed:', err);
            prompt('Copy this link:', text);
        }

        document.body.removeChild(textarea);
    }

    /**
     * Show toast notification
     * @param {string} message - Message to display
     * @param {string} type - Toast type
     */
    function showToast(message, type) {
        if (window.showToast && typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
