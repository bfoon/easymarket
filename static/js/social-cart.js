/**
 * Social Cart Management Module (FULL + Correct + Live)
 *
 * Fixes your current issues:
 * ✅ Handles 404/HTML responses properly (not always "login redirect")
 * ✅ Auto-recovers from stale social_id (clears storage, recreates, retries once)
 * ✅ Never relies on old localStorage as truth (server status is authoritative)
 * ✅ Adds LIVE activity updates (polling) so cart updates without refresh
 * ✅ Added approve/reject member handlers
 *
 * Required globals (set in Django template):
 *   window.CREATE_SOCIAL_CART_URL = "{% url 'marketplace:create_social_cart' %}";
 *   window.SEND_INVITE_URL       = "{% url 'marketplace:send_cart_invite' %}";
 *   window.SOCIAL_STATUS_URL     = "{% url 'marketplace:social_cart_status' %}";
 *   window.CART_SHARE_URL        = "{% url 'marketplace:share_cart' %}";
 *   window.LEAVE_CART_URL        = "{% url 'marketplace:leave_social_cart' %}";
 *   window.SET_SPLIT_MODE_URL    = "{% url 'marketplace:set_split_mode' %}";
 *   window.SOCIAL_CART_LIVE_URL  = "{% url 'marketplace:social_cart_live' %}";
 *
 * Optional:
 *   window.SOCIAL_LIVE_POLL_MS = 2500;
 *   window.showToast(message, type)
 *
 * DOM (optional but recommended):
 *   <div id="liveActivityFeed"></div>
 */

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Config
  // ---------------------------------------------------------------------------
  const STORAGE_KEYS = {
    SOCIAL_ID: "em_social_id",
    INVITE_LINK: "em_social_invite",
    LAST_ACTIVITY_ID: "em_social_last_activity_id",
  };

  const REQUEST_TIMEOUT_MS = 15000;
  const DEFAULT_POLL_MS = 2500;

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let socialId = null;
  let socialInviteLink = "";
  let socialQrCode = null;
  let csrfToken = "";

  // live
  let pollTimer = null;
  let lastActivityId = 0;
  let isPolling = false;

  // ---------------------------------------------------------------------------
  // DOM Elements
  // ---------------------------------------------------------------------------
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

    // QR
    qrCodeBtn: null,
    qrCodeImage: null,
    qrCodeModal: null,

    // Containers
    actionsWrap: null,
    ctaCard: null,
    serverCard: null,

    // Live feed
    liveFeed: null,

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
    currentSplitEl: null,
  };

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------
  function init() {
    csrfToken = getCSRFToken();
    initializeElements();
    initializeState().finally(() => {
      attachEventListeners();
      maybeStartLivePolling();
    });
  }

  function initializeElements() {
    // Buttons
    elements.createBtn = document.getElementById("createSocialCartBtn");
    elements.sendInviteBtn = document.getElementById("sendInviteBtn");
    elements.copyInviteBtn = document.getElementById("copyInviteBtn");
    elements.leaveBtn = document.getElementById("leaveCartBtn");

    // Inputs
    elements.inviteEmail = document.getElementById("inviteEmail");
    elements.invitePhone = document.getElementById("invitePhone");
    elements.inviteLinkEl = document.getElementById("socialInviteLink");
    elements.socialIdInput = document.getElementById("socialId");

    // QR
    elements.qrCodeBtn = document.getElementById("showSocialQrBtn");
    elements.qrCodeImage = document.getElementById("socialQrCodeImage");
    elements.qrCodeModal = document.getElementById("socialQrCodeModal");

    // Containers
    elements.actionsWrap = document.getElementById("socialCartActions");
    elements.ctaCard = document.getElementById("socialCtaCard");
    elements.serverCard = document.getElementById("socialServerCard");

    // Live feed container
    elements.liveFeed = document.getElementById("liveActivityFeed");

    // Split mode
    elements.btnSplitItems = document.getElementById("btnSplitItems");
    elements.btnSplitPercent = document.getElementById("btnSplitPercent");
    elements.btnSplitSingle = document.getElementById("btnSplitSingle");
    elements.percentBox = document.getElementById("percentBox");
    elements.payerBox = document.getElementById("payerBox");
    elements.btnApplyPercent = document.getElementById("btnApplyPercent");
    elements.btnApplySingle = document.getElementById("btnApplySingle");
    elements.singlePayerSel = document.getElementById("singlePayer");
    elements.pctInputs = document.querySelectorAll(".split-pct");
    elements.pctTotalHint = document.getElementById("pctTotalHint");
    elements.currentSplitEl = document.getElementById("currentSplitMode");
  }

  /**
   * State rules:
   * - server (hidden input) > status endpoint > localStorage
   * - localStorage is only cache
   */
  async function initializeState() {
    const serverSocialId = (elements.socialIdInput && elements.socialIdInput.value) || null;

    socialId = serverSocialId || localStorage.getItem(STORAGE_KEYS.SOCIAL_ID) || null;
    socialInviteLink = localStorage.getItem(STORAGE_KEYS.INVITE_LINK) || "";

    // Restore last activity cursor (live)
    lastActivityId = parseInt(localStorage.getItem(STORAGE_KEYS.LAST_ACTIVITY_ID) || "0", 10) || 0;

    // Try server status as truth
    try {
      const status = await fetchSocialStatus();
      if (status && status.social_id) {
        socialId = String(status.social_id);
        localStorage.setItem(STORAGE_KEYS.SOCIAL_ID, socialId);

        if (status.invite_link) {
          socialInviteLink = status.invite_link;
          localStorage.setItem(STORAGE_KEYS.INVITE_LINK, socialInviteLink);
          if (elements.inviteLinkEl) elements.inviteLinkEl.value = socialInviteLink;
        } else if (socialInviteLink && elements.inviteLinkEl) {
          elements.inviteLinkEl.value = socialInviteLink;
        }

        showSocialActions();
      } else {
        clearSocialCache();
        hideSocialActions();
      }
    } catch (e) {
      // status failed -> fallback to cached state best-effort
      if (socialId) {
        showSocialActions();
        if (socialInviteLink && elements.inviteLinkEl) elements.inviteLinkEl.value = socialInviteLink;
        fetchAndUpdateInviteLink().catch(() => {});
      } else {
        hideSocialActions();
      }
    }
  }

  function attachEventListeners() {
    if (elements.createBtn) elements.createBtn.addEventListener("click", handleCreateSocialCart);
    if (elements.sendInviteBtn) elements.sendInviteBtn.addEventListener("click", handleSendInvite);
    if (elements.copyInviteBtn) elements.copyInviteBtn.addEventListener("click", handleCopyInviteLink);
    if (elements.qrCodeBtn) elements.qrCodeBtn.addEventListener("click", handleShowSocialQrCode);
    if (elements.leaveBtn) elements.leaveBtn.addEventListener("click", handleLeaveCart);

    // Member management
    document.querySelectorAll(".js-remove-member").forEach((btn) => {
      btn.addEventListener("click", handleRemoveMember);
    });

    document.querySelectorAll(".js-approve-member").forEach((btn) => {
      btn.addEventListener("click", handleApproveMember);
    });

    document.querySelectorAll(".js-reject-member").forEach((btn) => {
      btn.addEventListener("click", handleRejectMember);
    });

    document.querySelectorAll(".js-block-member").forEach((btn) => {
      btn.addEventListener("click", handleBlockMember);
    });

    attachSplitModeListeners();

    // pause polling when tab hidden
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopLivePolling();
      else maybeStartLivePolling();
    });
  }

  function attachSplitModeListeners() {
    if (elements.btnSplitItems) elements.btnSplitItems.addEventListener("click", handleSplitByItems);
    if (elements.btnSplitPercent) elements.btnSplitPercent.addEventListener("click", showPercentBox);
    if (elements.btnSplitSingle) elements.btnSplitSingle.addEventListener("click", showPayerBox);

    if (elements.btnApplyPercent) elements.btnApplyPercent.addEventListener("click", handleApplyPercent);
    if (elements.btnApplySingle) elements.btnApplySingle.addEventListener("click", handleApplySinglePayer);

    if (elements.pctInputs && elements.pctInputs.length) {
      elements.pctInputs.forEach((input) => input.addEventListener("input", updatePercentageTotal));
      updatePercentageTotal();
    }
  }

  // ---------------------------------------------------------------------------
  // Core helpers (server sync + ensure social exists)
  // ---------------------------------------------------------------------------
  async function fetchSocialStatus() {
    const url = window.SOCIAL_STATUS_URL;
    if (!url) throw new Error("SOCIAL_STATUS_URL missing");

    return safeFetchJSON(url, { method: "GET" }, { timeoutMs: REQUEST_TIMEOUT_MS });
  }

  /**
   * Ensures a valid social cart exists.
   * - If stale ID: clears local cache and creates a new one.
   * - Always returns a valid socialId on success.
   */
  async function ensureSocialCartExists() {
    // Confirm existing via STATUS (authoritative)
    try {
      const st = await fetchSocialStatus();
      if (st && st.social_id) {
        socialId = String(st.social_id);
        localStorage.setItem(STORAGE_KEYS.SOCIAL_ID, socialId);

        if (st.invite_link) {
          socialInviteLink = st.invite_link;
          localStorage.setItem(STORAGE_KEYS.INVITE_LINK, socialInviteLink);
          if (elements.inviteLinkEl) elements.inviteLinkEl.value = socialInviteLink;
        }

        showSocialActions();
        return socialId;
      }
    } catch (_) {
      // ignore -> creation fallback
    }

    // Create new social cart
    const createUrl = window.CREATE_SOCIAL_CART_URL;
    if (!createUrl) throw new Error("CREATE_SOCIAL_CART_URL missing");

    const data = await safeFetchJSON(
      createUrl,
      {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken,
        },
      },
      { timeoutMs: REQUEST_TIMEOUT_MS }
    );

    if (!data || !data.success || !data.social_id) {
      throw new Error((data && (data.message || data.error)) || "Unable to create social cart");
    }

    socialId = String(data.social_id);
    localStorage.setItem(STORAGE_KEYS.SOCIAL_ID, socialId);

    if (data.invite_link) {
      socialInviteLink = data.invite_link;
      localStorage.setItem(STORAGE_KEYS.INVITE_LINK, socialInviteLink);
      if (elements.inviteLinkEl) elements.inviteLinkEl.value = socialInviteLink;
    } else {
      await fetchAndUpdateInviteLink();
    }

    showSocialActions();
    return socialId;
  }

  async function fetchAndUpdateInviteLink() {
    const shareUrl = window.CART_SHARE_URL;
    if (!shareUrl) throw new Error("CART_SHARE_URL missing");

    const data = await safeFetchJSON(shareUrl, { method: "GET" }, { timeoutMs: REQUEST_TIMEOUT_MS });

    if (data && (data.share_url || data.invite_link)) {
      socialInviteLink = data.share_url || data.invite_link;
      localStorage.setItem(STORAGE_KEYS.INVITE_LINK, socialInviteLink);
      if (elements.inviteLinkEl) elements.inviteLinkEl.value = socialInviteLink;
    }

    if (data && data.qr_code) {
      socialQrCode = data.qr_code;
    }

    return data;
  }

  // ---------------------------------------------------------------------------
  // UI helpers
  // ---------------------------------------------------------------------------
  function showSocialActions() {
    if (elements.actionsWrap) elements.actionsWrap.style.display = "block";
    if (elements.ctaCard) elements.ctaCard.style.display = "none";
  }

  function hideSocialActions() {
    if (elements.actionsWrap) elements.actionsWrap.style.display = "none";
    if (elements.ctaCard) elements.ctaCard.style.display = "block";
  }

  function clearSocialCache() {
    socialId = null;
    socialInviteLink = "";
    socialQrCode = null;

    localStorage.removeItem(STORAGE_KEYS.SOCIAL_ID);
    localStorage.removeItem(STORAGE_KEYS.INVITE_LINK);

    if (elements.inviteLinkEl) elements.inviteLinkEl.value = "";
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------
  async function handleCreateSocialCart() {
    const btn = elements.createBtn;
    if (!btn) return;

    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating...';

    try {
      await ensureSocialCartExists();
      showToast("Social cart created! Share the link with friends.", "success");
      maybeStartLivePolling(true);
    } catch (error) {
      console.error("Error creating social cart:", error);
      showToast(error.message || "Error creating social cart", "danger");
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHTML;
    }
  }

  /**
   * Invite send with recovery:
   * - If server says invalid/expired social cart, clear cache, recreate, retry once.
   */
  async function handleSendInvite() {
    const email = (elements.inviteEmail && elements.inviteEmail.value ? elements.inviteEmail.value : "").trim();
    const phone = (elements.invitePhone && elements.invitePhone.value ? elements.invitePhone.value : "").trim();

    if (!email && !phone) {
      showToast("Enter an email or phone number", "warning");
      return;
    }

    const btn = elements.sendInviteBtn;
    const originalHTML = btn ? btn.innerHTML : "";

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    }

    try {
      await ensureSocialCartExists();

      const inviteUrl = window.SEND_INVITE_URL;
      if (!inviteUrl) throw new Error("SEND_INVITE_URL missing");

      const data = await safeFetchJSON(
        inviteUrl,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRFToken": csrfToken,
          },
          body: new URLSearchParams({
            email,
            phone,
            social_id: socialId,
          }),
        },
        { timeoutMs: REQUEST_TIMEOUT_MS }
      );

      if (!data || !data.success) {
        throw new Error((data && (data.message || data.error)) || "Failed to send invite");
      }

      if (data.invite_link) {
        socialInviteLink = data.invite_link;
        localStorage.setItem(STORAGE_KEYS.INVITE_LINK, socialInviteLink);
        if (elements.inviteLinkEl) elements.inviteLinkEl.value = socialInviteLink;
      }

      if (elements.inviteEmail) elements.inviteEmail.value = "";
      if (elements.invitePhone) elements.invitePhone.value = "";

      showToast("Invitation sent successfully!", "success");
      return;

    } catch (error) {
      console.error("Error sending invite:", error);

      const msg = String(error.message || "");

      // ✅ Recovery for stale/invalid social cart (common cause of 404 HTML)
      const looksLikeStale =
        msg.toLowerCase().includes("invalid") ||
        msg.toLowerCase().includes("expired") ||
        msg.toLowerCase().includes("not found");

      if (looksLikeStale) {
        clearSocialCache();
        try {
          await ensureSocialCartExists();
          // retry once
          const inviteUrl = window.SEND_INVITE_URL;
          const data2 = await safeFetchJSON(
            inviteUrl,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrfToken,
              },
              body: new URLSearchParams({
                email,
                phone,
                social_id: socialId,
              }),
            },
            { timeoutMs: REQUEST_TIMEOUT_MS }
          );

          if (!data2 || !data2.success) {
            throw new Error((data2 && (data2.message || data2.error)) || "Failed to send invite");
          }

          showToast("Invitation sent successfully!", "success");
          return;
        } catch (e2) {
          console.error("Retry failed:", e2);
          showToast(e2.message || "Error sending invite", "danger");
        }
      } else {
        showToast(msg || "Error sending invite", "danger");
      }

    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = originalHTML;
      }
    }
  }

  function handleCopyInviteLink() {
    const linkToCopy =
      (elements.inviteLinkEl && elements.inviteLinkEl.value) ||
      localStorage.getItem(STORAGE_KEYS.INVITE_LINK);

    if (!linkToCopy) {
      showToast("No invite link available", "warning");
      return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard
        .writeText(linkToCopy)
        .then(() => showToast("Invite link copied!", "success"))
        .catch(() => fallbackCopyText(linkToCopy));
    } else {
      fallbackCopyText(linkToCopy);
    }
  }

  async function handleShowSocialQrCode() {
    try {
      await ensureSocialCartExists();

      if (!socialQrCode) {
        await fetchAndUpdateInviteLink();
      }

      if (!socialQrCode) {
        showToast("QR code not available yet. Try again.", "info");
        return;
      }

      if (elements.qrCodeImage) {
        elements.qrCodeImage.src = `data:image/png;base64,${socialQrCode}`;
      }

      if (elements.qrCodeModal && typeof bootstrap !== "undefined") {
        const modal = new bootstrap.Modal(elements.qrCodeModal);
        modal.show();
      } else if (elements.qrCodeModal) {
        elements.qrCodeModal.style.display = "block";
        elements.qrCodeModal.classList.add("show");
      }
    } catch (error) {
      console.error("QR error:", error);
      showToast(error.message || "Could not generate QR", "danger");
    }
  }

  async function handleLeaveCart() {
    if (!confirm("Leave this collaborative cart?")) return;

    const btn = elements.leaveBtn;
    const originalHTML = btn ? btn.innerHTML : "";

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Leaving...';
    }

    try {
      await ensureSocialCartExists();

      const leaveUrl = window.LEAVE_CART_URL;
      if (!leaveUrl) throw new Error("LEAVE_CART_URL missing");

      const data = await safeFetchJSON(
        leaveUrl,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRFToken": csrfToken,
          },
          body: new URLSearchParams({ social_id: socialId }),
        },
        { timeoutMs: REQUEST_TIMEOUT_MS }
      );

      if (!data || !data.success) {
        throw new Error((data && (data.message || data.error)) || "Failed to leave cart");
      }

      stopLivePolling();
      clearSocialCache();
      hideSocialActions();

      if (elements.serverCard) elements.serverCard.style.display = "none";
      showToast("You have left the cart", "info");
    } catch (error) {
      console.error("Error leaving cart:", error);
      showToast(error.message || "Error leaving cart", "danger");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = originalHTML;
      }
    }
  }

  async function handleRemoveMember(event) {
    const btn = event.currentTarget;
    const url = btn && btn.dataset ? btn.dataset.removeUrl : null;

    if (!url) {
      showToast("Invalid remove URL", "danger");
      return;
    }

    if (!confirm("Remove this member from the social cart? Their items may be removed.")) return;

    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
      const data = await safeFetchJSON(
        url,
        { method: "POST", headers: { "X-CSRFToken": csrfToken } },
        { timeoutMs: REQUEST_TIMEOUT_MS }
      );

      if (!data || !data.success) throw new Error((data && (data.message || data.error)) || "Failed to remove member");

      showToast("Member removed successfully", "success");
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      console.error("Error removing member:", error);
      showToast(error.message || "Error removing member", "danger");
      btn.disabled = false;
      btn.innerHTML = originalHTML;
    }
  }

  /**
   * NEW: Handle approve member
   */
  async function handleApproveMember(event) {
    const btn = event.currentTarget;
    const url = btn && btn.dataset ? btn.dataset.url : null;

    if (!url) {
      showToast("Invalid approval URL", "danger");
      return;
    }

    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
      const data = await safeFetchJSON(
        url,
        { method: "POST", headers: { "X-CSRFToken": csrfToken } },
        { timeoutMs: REQUEST_TIMEOUT_MS }
      );

      if (!data || !data.success) {
        throw new Error((data && (data.message || data.error)) || "Failed to approve member");
      }

      showToast(data.message || "Member approved successfully", "success");
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      console.error("Error approving member:", error);
      showToast(error.message || "Error approving member", "danger");
      btn.disabled = false;
      btn.innerHTML = originalHTML;
    }
  }

  /**
   * NEW: Handle reject member
   */
  async function handleRejectMember(event) {
    const btn = event.currentTarget;
    const url = btn && btn.dataset ? btn.dataset.url : null;

    if (!url) {
      showToast("Invalid rejection URL", "danger");
      return;
    }

    if (!confirm("Reject this member's request to join?")) return;

    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
      const data = await safeFetchJSON(
        url,
        { method: "POST", headers: { "X-CSRFToken": csrfToken } },
        { timeoutMs: REQUEST_TIMEOUT_MS }
      );

      if (!data || !data.success) {
        throw new Error((data && (data.message || data.error)) || "Failed to reject member");
      }

      showToast(data.message || "Member rejected", "info");
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      console.error("Error rejecting member:", error);
      showToast(error.message || "Error rejecting member", "danger");
      btn.disabled = false;
      btn.innerHTML = originalHTML;
    }
  }

  /**
   * NEW: Handle block member (for joined members)
   */
  async function handleBlockMember(event) {
    const btn = event.currentTarget;
    const url = btn && btn.dataset ? btn.dataset.url : null;

    if (!url) {
      showToast("Invalid block URL", "danger");
      return;
    }

    if (!confirm("Block this member? They will be removed and cannot rejoin unless unblocked.")) return;

    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
      const data = await safeFetchJSON(
        url,
        { method: "POST", headers: { "X-CSRFToken": csrfToken } },
        { timeoutMs: REQUEST_TIMEOUT_MS }
      );

      if (!data || !data.success) {
        throw new Error((data && (data.message || data.error)) || "Failed to block member");
      }

      showToast(data.message || "Member blocked successfully", "warning");
      setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      console.error("Error blocking member:", error);
      showToast(error.message || "Error blocking member", "danger");
      btn.disabled = false;
      btn.innerHTML = originalHTML;
    }
  }

  // ---------------------------------------------------------------------------
  // Split mode handlers
  // ---------------------------------------------------------------------------
  async function handleSplitByItems() {
    hideAllSplitBoxes();

    try {
      await ensureSocialCartExists();
      const data = await postSplitMode({ mode: "by_items", social_id: socialId });
      if (!data.success) throw new Error(data.message || "Failed to set split");

      if (elements.currentSplitEl) elements.currentSplitEl.textContent = "By Items";
      showToast("Split set: Each pays their items", "success");
    } catch (error) {
      console.error("Error setting split mode:", error);
      showToast(error.message || "Error setting split", "danger");
    }
  }

  function showPercentBox() {
    hideAllSplitBoxes();
    if (elements.percentBox) elements.percentBox.style.display = "block";
  }

  function showPayerBox() {
    hideAllSplitBoxes();
    if (elements.payerBox) elements.payerBox.style.display = "block";
  }

  function hideAllSplitBoxes() {
    if (elements.percentBox) elements.percentBox.style.display = "none";
    if (elements.payerBox) elements.payerBox.style.display = "none";
  }

  function updatePercentageTotal() {
    if (!elements.pctInputs || !elements.pctInputs.length) return;

    let total = 0;
    elements.pctInputs.forEach((input) => {
      const val = parseFloat(input.value) || 0;
      total += val;
    });

    if (elements.pctTotalHint) {
      const color = total === 100 ? "text-success" : "text-danger";
      elements.pctTotalHint.textContent = `Total: ${total.toFixed(1)}%`;
      elements.pctTotalHint.className = `text-muted ms-2 ${color}`;
    }
  }

  async function handleApplyPercent() {
    if (!elements.pctInputs || !elements.pctInputs.length) {
      showToast("No percentage inputs found", "warning");
      return;
    }

    const allocations = {};
    let total = 0;

    elements.pctInputs.forEach((input) => {
      const memberId = input.dataset.memberId;
      const val = parseFloat(input.value) || 0;
      if (memberId) {
        allocations[memberId] = val;
        total += val;
      }
    });

    if (Math.abs(total - 100) > 0.01) {
      showToast("Percentages must total 100%", "warning");
      return;
    }

    try {
      await ensureSocialCartExists();
      const data = await postSplitMode({
        mode: "by_percent",
        social_id: socialId,
        allocations: JSON.stringify(allocations),
      });

      if (!data.success) throw new Error(data.message || "Failed to set split");

      if (elements.currentSplitEl) elements.currentSplitEl.textContent = "Percent";
      showToast("Split set: Pay by percentage", "success");
    } catch (error) {
      console.error("Error setting percentages:", error);
      showToast(error.message || "Error setting split", "danger");
    }
  }

  async function handleApplySinglePayer() {
    if (!elements.singlePayerSel) {
      showToast("No payer selector found", "warning");
      return;
    }

    const payerId = elements.singlePayerSel.value;
    if (!payerId) {
      showToast("Please select a payer", "warning");
      return;
    }

    try {
      await ensureSocialCartExists();
      const data = await postSplitMode({
        mode: "single_payer",
        social_id: socialId,
        payer_member_id: payerId,
      });

      if (!data.success) throw new Error(data.message || "Failed to set split");

      if (elements.currentSplitEl) elements.currentSplitEl.textContent = "Single Payer";
      showToast("Split set: One person pays full", "success");
    } catch (error) {
      console.error("Error setting single payer:", error);
      showToast(error.message || "Error setting split", "danger");
    }
  }

  async function postSplitMode(payload) {
    const splitUrl = window.SET_SPLIT_MODE_URL;
    if (!splitUrl) throw new Error("SET_SPLIT_MODE_URL missing");

    return safeFetchJSON(
      splitUrl,
      {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken,
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams(payload),
      },
      { timeoutMs: REQUEST_TIMEOUT_MS }
    );
  }

  // ---------------------------------------------------------------------------
  // LIVE ACTIVITY POLLING (no refresh needed)
  // ---------------------------------------------------------------------------
  function maybeStartLivePolling(force = false) {
    if (!window.SOCIAL_CART_LIVE_URL) return;
    if (!socialId && !force) return;

    if (isPolling) return;

    const pollMs = Number(window.SOCIAL_LIVE_POLL_MS || DEFAULT_POLL_MS);
    isPolling = true;

    // immediate poll
    pollLive().catch(() => {});

    pollTimer = setInterval(() => {
      pollLive().catch(() => {});
    }, pollMs);
  }

  function stopLivePolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    isPolling = false;
  }

  async function pollLive() {
    if (!window.SOCIAL_CART_LIVE_URL) return;
    if (!socialId) return;

    const qs = new URLSearchParams({
      social_id: String(socialId),
      since: String(lastActivityId || 0),
    });

    const data = await safeFetchJSON(
      `${window.SOCIAL_CART_LIVE_URL}?${qs.toString()}`,
      { method: "GET" },
      { timeoutMs: REQUEST_TIMEOUT_MS }
    );

    if (!data || !data.success) return;

    const acts = Array.isArray(data.activities) ? data.activities : [];
    if (!acts.length) return;

    // Update cursor (assume activities are ascending or mixed; take max)
    const maxId = acts.reduce((m, a) => Math.max(m, Number(a.id || 0)), lastActivityId || 0);
    lastActivityId = maxId;
    localStorage.setItem(STORAGE_KEYS.LAST_ACTIVITY_ID, String(lastActivityId));

    // Render in feed (and toast)
    acts.forEach((a) => {
      appendActivity(a);
    });
  }

  function appendActivity(a) {
    // Extract message - it should already contain the full text
    const msg = a.message || a.event || "Activity update";

    // Don't add "undefined:" prefix - the message already has the format
    const displayText = msg;

    // Only show toast for actual new activities, not "undefined" messages
    if (!msg.toLowerCase().includes('undefined')) {
      showToast(displayText, "info");
    }

    // feed list
    if (!elements.liveFeed) return;

    const div = document.createElement("div");
    div.className = "small py-1 border-bottom text-muted";
    div.innerHTML = `<i class="fas fa-circle me-1" style="font-size:6px;"></i>${displayText}`;
    elements.liveFeed.prepend(div);

    // keep feed short (last 50)
    while (elements.liveFeed.children.length > 50) {
      elements.liveFeed.removeChild(elements.liveFeed.lastChild);
    }
  }

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------
  function getCSRFToken() {
    if (window.getCSRFToken && typeof window.getCSRFToken === "function") return window.getCSRFToken();

    let token = getCookie("csrftoken");
    if (!token) {
      const tokenInput = document.querySelector('[name="csrfmiddlewaretoken"]');
      if (tokenInput) token = tokenInput.value;
    }
    return token || "";
  }

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function fallbackCopyText(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";

    document.body.appendChild(textarea);
    textarea.select();

    try {
      document.execCommand("copy");
      showToast("Invite link copied!", "success");
    } catch (err) {
      console.error("Copy failed:", err);
      prompt("Copy this link:", text);
    }

    document.body.removeChild(textarea);
  }

  function showToast(message, type) {
    if (window.showToast && typeof window.showToast === "function") {
      window.showToast(message, type);
    } else {
      console.log(`[${String(type || "info").toUpperCase()}] ${message}`);
    }
  }

  /**
   * Safe fetch JSON helper:
   * - Same-origin credentials
   * - Timeout protection
   * - Better error for HTML (could be 404 page, login page, error page)
   */
  async function safeFetchJSON(url, options = {}, extra = {}) {
    const timeoutMs = extra.timeoutMs || REQUEST_TIMEOUT_MS;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const fetchOptions = {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.headers || {}),
        "X-Requested-With": "XMLHttpRequest",
      },
      signal: controller.signal,
    };

    try {
      const res = await fetch(url, fetchOptions);

      // parse json if possible, else read text and throw
      const ct = (res.headers.get("content-type") || "").toLowerCase();

      if (ct.includes("application/json")) {
        const data = await res.json();
        if (!res.ok) {
          throw new Error((data && (data.message || data.error)) || `Request failed (${res.status})`);
        }
        return data;
      }

      // Not json -> likely HTML (404 page, login redirect, server error)
      const text = await res.text();
      if (!res.ok) {
        // give useful hint
        if (text && text.toLowerCase().includes("<html")) {
          throw new Error(`Request failed (${res.status}). Server returned HTML (check URL/auth/error).`);
        }
        throw new Error(text || `Request failed (${res.status})`);
      }

      // ok but not json
      throw new Error("Server returned unexpected response (not JSON).");
    } catch (err) {
      if (err && err.name === "AbortError") throw new Error("Request timed out. Please try again.");
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  (function () {
  const btnSplitSingle = document.getElementById("btnSplitSingle");
  const btnSplitItems = document.getElementById("btnSplitItems");
  const btnSplitPercent = document.getElementById("btnSplitPercent");

  const payerBox = document.getElementById("payerBox");
  const percentBox = document.getElementById("percentBox");

  const btnApplySingle = document.getElementById("btnApplySingle");
  const singlePayer = document.getElementById("singlePayer");

  if (!window.SET_SPLIT_MODE_URL) return;

  function csrfToken() {
    return document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  }

  function hideAll() {
    if (payerBox) payerBox.style.display = "none";
    if (percentBox) percentBox.style.display = "none";
  }

  // Show payer selector
  btnSplitSingle?.addEventListener("click", () => {
    hideAll();
    payerBox.style.display = "block";
  });

  // Apply single payer
  btnApplySingle?.addEventListener("click", async () => {
    const payerId = singlePayer?.value;
    if (!payerId) {
      alert("Please select a payer");
      return;
    }

    const fd = new FormData();
    fd.append("mode", "single_payer");
    fd.append("payer_member_id", payerId);

    const res = await fetch(window.SET_SPLIT_MODE_URL, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken() },
      body: fd,
      credentials: "same-origin",
    });

    const data = await res.json();
    if (!data.success) {
      alert(data.message || "Failed to set payer");
      return;
    }

    location.reload();
  });
})();
(function () {
  const btn = document.getElementById("btnApplyCheckoutMembers");
  if (!btn || !window.SET_CHECKOUT_MEMBERS_URL) return;

  function csrfToken() {
    return document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  }

  btn.addEventListener("click", async () => {
    const checks = Array.from(document.querySelectorAll(".js-checkout-member"));
    const selectedIds = checks.filter(c => c.checked).map(c => c.value);

    const socialId = document.getElementById("socialId")?.value;
    if (!socialId) {
      alert("Missing social cart id.");
      return;
    }

    const fd = new FormData();
    fd.append("social_id", socialId);
    selectedIds.forEach(id => fd.append("member_ids[]", id));

    const res = await fetch(window.SET_CHECKOUT_MEMBERS_URL, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken() },
      body: fd,
      credentials: "same-origin",
    });

    const data = await res.json();
    if (!data.success) {
      alert(data.message || "Failed to update checkout members.");
      return;
    }

    // optional toast
    if (window.showToast) window.showToast("Checkout members saved.", "success");
    else alert("Checkout members saved.");
  });
})();

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();