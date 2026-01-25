/**
 * cart-page-complete.js - CORRECTED VERSION
 * 
 * Consolidated and fixed JavaScript for social cart functionality
 * - Removed duplicate functions
 * - Fixed event binding issues
 * - Proper CSRF handling
 * - Consolidated helper functions
 */

(function () {
  'use strict';

  // =========================
  // GLOBAL HELPERS (SINGLE INSTANCE)
  // =========================
  
  function getCSRFToken() {
    const name = "csrftoken=";
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (let c of cookies) {
      c = c.trim();
      if (c.startsWith(name)) return decodeURIComponent(c.substring(name.length));
    }
    return "";
  }

  // Expose globally for backward compatibility
  window.getCookie = function(name) {
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
  };

  // Toast notification (single instance)
  if (!window.showToast) {
    window.showToast = function (message, type = "info") {
      const alertClass =
        type === "error" ? "danger" :
        type === "success" ? "success" :
        type === "warning" ? "warning" : "info";

      const toast = document.createElement("div");
      toast.className = `alert alert-${alertClass} alert-dismissible fade show position-fixed top-0 end-0 m-3`;
      toast.style.zIndex = "9999";
      toast.style.minWidth = "300px";
      toast.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
      `;
      document.body.appendChild(toast);
      setTimeout(() => toast.remove(), 3000);
    };
  }

  // Fetch helpers
  async function postForm(url, dataObj) {
    const body = new URLSearchParams();
    Object.entries(dataObj || {}).forEach(([k, v]) => body.append(k, v));

    const res = await fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCSRFToken(),
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: body.toString(),
      credentials: "same-origin",
    });

    const data = await res.json().catch(() => null);
    if (!data) throw new Error("Server did not return JSON (maybe redirected).");
    return data;
  }

  async function getJSON(url) {
    const res = await fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
    const data = await res.json().catch(() => null);
    if (!data) throw new Error("Server did not return JSON.");
    return data;
  }

  function urlFromTpl(tpl, id) {
    return tpl.replace(/0\/?$/, String(id) + "/").replace("=0", "=" + String(id));
  }

  function safeBind(el, key, fn) {
    if (!el) return false;
    if (el.dataset[key] === "1") return false;
    el.dataset[key] = "1";
    el.addEventListener("click", fn);
    return true;
  }

  function escapeHtml(s) {
    return String(s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // =========================
  // START SOCIAL CART
  // =========================
  
  function bindStartSocialCartButton() {
    const btn = document.getElementById("createSocialCartBtn");
    if (!btn) return;

    safeBind(btn, "boundStart", (e) => {
      e.preventDefault();
      const modalEl = document.getElementById("startSocialCartModal");
      if (!modalEl) return window.showToast("Start Social Cart modal not found.", "error");

      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
    });
  }

  function bindStartSocialCartModal() {
    // Schedule toggle
    const scToggle = document.getElementById("scScheduleToggle");
    const scBox = document.getElementById("scScheduleBox");
    if (scToggle && scBox && scToggle.dataset.bound !== "1") {
      scToggle.dataset.bound = "1";
      scToggle.addEventListener("change", () => {
        scBox.style.display = scToggle.checked ? "block" : "none";
      });
    }

    // Start button
    const scStartBtn = document.getElementById("scStartBtn");
    if (!scStartBtn) return;

    safeBind(scStartBtn, "boundStartModal", async () => {
      if (!window.CREATE_SOCIAL_CART_URL) {
        return window.showToast("CREATE_SOCIAL_CART_URL missing", "error");
      }

      const accessType = (document.querySelector('input[name="scAccessType"]:checked') || {}).value || "public";
      const scheduled = !!document.getElementById("scScheduleToggle")?.checked;
      const scheduledFor = (document.getElementById("scScheduledFor")?.value || "").trim();

      try {
        scStartBtn.disabled = true;
        scStartBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating...';

        // Create social cart
        const created = await postForm(window.CREATE_SOCIAL_CART_URL, { access_type: accessType });
        if (!created.success) throw new Error(created.message || "Could not create social cart");

        // Schedule if needed
        if (scheduled) {
          if (!scheduledFor) throw new Error("Please choose a start time.");
          if (window.SCHEDULE_SOCIAL_CART_URL) {
            const sch = await postForm(window.SCHEDULE_SOCIAL_CART_URL, {
              scheduled_for: scheduledFor,
              access_type: accessType
            });
            if (!sch.success) throw new Error(sch.message || "Could not schedule social cart");
          } else {
            window.showToast("Schedule endpoint not available", "warning");
          }
        }

        // Close modal and reload
        const modalEl = document.getElementById("startSocialCartModal");
        if (modalEl) bootstrap.Modal.getInstance(modalEl)?.hide();

        window.showToast("Social cart ready ✅", "success");
        setTimeout(() => window.location.reload(), 600);
      } catch (e) {
        window.showToast(e.message || "Failed", "error");
      } finally {
        scStartBtn.disabled = false;
        scStartBtn.innerHTML = '<i class="fas fa-play me-1"></i>Start';
      }
    });
  }

  // =========================
  // MANAGE MEMBERS MODAL
  // =========================
  
  function setCount(id, n) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(n ?? 0);
  }

  function renderPending(listEl, pending) {
    if (!listEl) return;
    if (!pending || !pending.length) {
      listEl.innerHTML = `<div class="text-muted small">No pending requests.</div>`;
      return;
    }

    listEl.innerHTML = pending.map(m => `
      <div class="list-group-item d-flex justify-content-between align-items-center">
        <div>
          <div class="fw-semibold">${escapeHtml(m.name || m.username || "Member")}</div>
          <div class="small text-muted">${escapeHtml(m.email || "")}</div>
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-sm btn-success mm-approve-member" data-member-id="${m.id}">
            <i class="fas fa-check me-1"></i>Admit
          </button>
          <button class="btn btn-sm btn-outline-danger mm-reject-member" data-member-id="${m.id}">
            <i class="fas fa-times me-1"></i>Reject
          </button>
        </div>
      </div>
    `).join("");

    listEl.querySelectorAll(".mm-approve-member").forEach(btn => {
      btn.addEventListener("click", async () => {
        try {
          const id = btn.dataset.memberId;
          const url = urlFromTpl(window.APPROVE_MEMBER_URL_TPL, id);
          const r = await postForm(url, {});
          if (!r.success) throw new Error(r.message || "Failed to admit");
          window.showToast("Member admitted ✅", "success");
          await refreshMembersPanel();
        } catch (e) {
          window.showToast(e.message || "Error", "error");
        }
      });
    });

    listEl.querySelectorAll(".mm-reject-member").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Reject this request?")) return;
        try {
          const id = btn.dataset.memberId;
          const url = urlFromTpl(window.REJECT_MEMBER_URL_TPL, id);
          const r = await postForm(url, {});
          if (!r.success) throw new Error(r.message || "Failed to reject");
          window.showToast("Request rejected ✅", "success");
          await refreshMembersPanel();
        } catch (e) {
          window.showToast(e.message || "Error", "error");
        }
      });
    });
  }

  function renderInvites(listEl, invites) {
    if (!listEl) return;
    if (!invites || !invites.length) {
      listEl.innerHTML = `<div class="text-muted small">No pending invites.</div>`;
      return;
    }

    listEl.innerHTML = invites.map(inv => `
      <div class="list-group-item d-flex justify-content-between align-items-center">
        <div class="flex-grow-1">
          <div class="fw-semibold">${escapeHtml(inv.invited_email || inv.invited_phone || "Invite")}</div>
          <div class="small text-muted">
            Sent: ${inv.created_at ? new Date(inv.created_at).toLocaleString() : "—"}<br>
            Expires: ${inv.expires_at ? new Date(inv.expires_at).toLocaleString() : "—"}
          </div>
        </div>
        <div class="d-flex gap-2 align-items-center">
          <span class="badge bg-info text-dark">Pending</span>
          <button class="btn btn-sm btn-outline-danger mm-delete-invite"
                  data-invite-id="${inv.id}"
                  title="Delete invitation">
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
    `).join("");

    listEl.querySelectorAll(".mm-delete-invite").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this invitation? The recipient will no longer be able to join using this invite.")) return;
        if (!window.DELETE_INVITE_URL_TPL) return window.showToast("DELETE_INVITE_URL_TPL not set", "error");

        try {
          const inviteId = btn.dataset.inviteId;
          const url = urlFromTpl(window.DELETE_INVITE_URL_TPL, inviteId);
          const r = await postForm(url, {});
          if (!r.success) throw new Error(r.message || "Failed to delete invite");

          window.showToast(r.message || "Invitation deleted ✅", "success");
          await refreshMembersPanel();
        } catch (e) {
          window.showToast(e.message || "Error", "error");
        }
      });
    });
  }


  function renderMembers(listEl, members) {
    if (!listEl) return;
    if (!members || !members.length) {
      listEl.innerHTML = `<div class="text-muted small">No members yet.</div>`;
      return;
    }

    const currentUserId = String(window.CURRENT_USER_ID || "");
    const isOwner = !!window.IS_OWNER;

    listEl.innerHTML = members.map(m => {
      const memberId = String(m.id);
      const username = String(m.username || "");
      const isCurrentUser = (currentUserId && (memberId === currentUserId || username === currentUserId));
      const isMemberOwner = (m.role === "owner");
      const isBlocked = (m.status === "blocked");

      // Owner can manage anyone except themselves and (optionally) other owners
      const canManage = isOwner && !isCurrentUser && !isMemberOwner;

      return `
        <div class="list-group-item">
          <div class="d-flex align-items-center justify-content-between gap-2">
            <div class="flex-grow-1">
              <div class="d-flex align-items-center gap-2 flex-wrap">
                <div class="fw-semibold">${escapeHtml(m.name || m.username || "Member")}</div>
                ${isMemberOwner ? '<span class="badge bg-warning text-dark"><i class="fas fa-crown me-1"></i>Owner</span>' : ''}
                ${isBlocked ? '<span class="badge bg-danger"><i class="fas fa-ban me-1"></i>Blocked</span>' : ''}
                ${isCurrentUser ? '<span class="badge bg-primary"><i class="fas fa-user me-1"></i>You</span>' : ''}
              </div>
              <div class="small text-muted">${escapeHtml(m.email || "")}</div>
            </div>

            ${canManage ? `
              <div class="btn-group btn-group-sm">
                ${!isBlocked ? `
                  <button class="btn btn-outline-warning mm-block-member"
                          data-member-id="${memberId}"
                          data-member-name="${escapeHtml(m.name || m.username || "member")}">
                    <i class="fas fa-ban me-1"></i>Block
                  </button>
                ` : ``}
                <button class="btn btn-outline-danger mm-remove-member"
                        data-member-id="${memberId}"
                        data-member-name="${escapeHtml(m.name || m.username || "member")}">
                  <i class="fas fa-user-times me-1"></i>Remove
                </button>
              </div>
            ` : `
              <span class="badge bg-success">Joined</span>
            `}
          </div>
        </div>
      `;
    }).join("");

    // Bind remove
    listEl.querySelectorAll(".mm-remove-member").forEach(btn => {
      btn.addEventListener("click", async () => {
        const memberId = btn.dataset.memberId;
        const name = btn.dataset.memberName;

        const msg =
          `Remove ${name || "this member"} from the social cart?

` +
          `Their items will be moved to their personal cart.
` +
          `They can be re-invited later.`;
        if (!confirm(msg)) return;

        if (!window.REMOVE_MEMBER_URL_TPL) return window.showToast("REMOVE_MEMBER_URL_TPL not set", "error");

        try {
          const url = urlFromTpl(window.REMOVE_MEMBER_URL_TPL, memberId);
          const r = await postForm(url, {});
          if (!r.success) throw new Error(r.message || "Failed to remove member");

          window.showToast(r.message || "Member removed ✅", "success");
          await refreshMembersPanel();
          setTimeout(() => window.location.reload(), 700);
        } catch (e) {
          window.showToast(e.message || "Error", "error");
        }
      });
    });

    // Bind block
    listEl.querySelectorAll(".mm-block-member").forEach(btn => {
      btn.addEventListener("click", async () => {
        const memberId = btn.dataset.memberId;
        const name = btn.dataset.memberName;

        const msg =
          `Block ${name || "this member"}?

` +
          `⚠️ They will be removed from the cart
` +
          `⚠️ They cannot rejoin unless unblocked
` +
          `⚠️ Their items will be moved to their personal cart

` +
          `Continue?`;
        if (!confirm(msg)) return;

        if (!window.BLOCK_MEMBER_URL_TPL) return window.showToast("BLOCK_MEMBER_URL_TPL not set", "error");

        try {
          const url = urlFromTpl(window.BLOCK_MEMBER_URL_TPL, memberId);
          const r = await postForm(url, {});
          if (!r.success) throw new Error(r.message || "Failed to block member");

          window.showToast(r.message || "Member blocked ✅", "warning");
          await refreshMembersPanel();
          setTimeout(() => window.location.reload(), 700);
        } catch (e) {
          window.showToast(e.message || "Error", "error");
        }
      });
    });
  }


  async function refreshMembersPanel() {
    if (!window.SOCIAL_STATUS_URL) return;

    const pendingList = document.getElementById("mmPendingList");
    const invitesList = document.getElementById("mmInvitesList");
    const membersList = document.getElementById("mmMembersList");

    try {
      const data = await getJSON(window.SOCIAL_STATUS_URL);

      const p = data.pending_members || [];
      const i = data.pending_invites || [];
      const m = data.members || [];

      setCount("mmPendingCount", p.length);
      setCount("mmInviteCount", i.length);
      setCount("mmMemberCount", m.length);

      renderPending(pendingList, p);
      renderInvites(invitesList, i);
      renderMembers(membersList, m);
    } catch (e) {
      if (pendingList) pendingList.innerHTML = `<div class="text-danger small">Failed to load members.</div>`;
    }
  }

  function bindManageMembersModal() {
    const emailEl = document.getElementById("mmInviteEmail");
    const phoneEl = document.getElementById("mmInvitePhone");
    const sendBtn = document.getElementById("mmSendInviteBtn");
    const clearBtn = document.getElementById("mmClearInviteBtn");
    const refreshBtn = document.getElementById("mmRefreshBtn");
    const modalEl = document.getElementById("manageMembersModal");

    if (sendBtn) {
      safeBind(sendBtn, "boundInvite", async () => {
        if (!window.SEND_INVITE_URL) return window.showToast("SEND_INVITE_URL not set", "error");

        const email = (emailEl?.value || "").trim();
        const phone = (phoneEl?.value || "").trim();

        if (!email && !phone) return window.showToast("Enter an email or phone number.", "error");
        if (email && phone) return window.showToast("Use either email OR phone (not both).", "error");

        try {
          sendBtn.disabled = true;
          sendBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>Sending...`;

          const r = await postForm(window.SEND_INVITE_URL, { email, phone });
          if (!r.success) throw new Error(r.message || "Invite failed");

          window.showToast(r.message || "Invite sent ✅", "success");
          if (emailEl) emailEl.value = "";
          if (phoneEl) phoneEl.value = "";

          await refreshMembersPanel();
        } catch (e) {
          window.showToast(e.message || "Invite failed", "error");
        } finally {
          sendBtn.disabled = false;
          sendBtn.innerHTML = `<i class="fas fa-paper-plane me-1"></i>Send Invite`;
        }
      });
    }

    if (clearBtn) {
      safeBind(clearBtn, "boundClearInvite", () => {
        if (emailEl) emailEl.value = "";
        if (phoneEl) phoneEl.value = "";
      });
    }

    if (refreshBtn) {
      safeBind(refreshBtn, "boundRefresh", refreshMembersPanel);
    }

    if (modalEl && modalEl.dataset.boundOpen !== "1") {
      modalEl.dataset.boundOpen = "1";
      modalEl.addEventListener("shown.bs.modal", refreshMembersPanel);
    }
  }


  // =========================
  // LEAVE CART BUTTONS
  // =========================
  
  function bindLeaveCart() {
  const leaveBtn = document.getElementById("leaveSocialCartBtn");
  const checkoutBtn = document.getElementById("leaveAndCheckoutBtn");

  // Regular Leave Button
  if (leaveBtn) {
    safeBind(leaveBtn, "boundLeave", async () => {   // ✅ FIXED (leaveBtn, not btn)
      const isOwner = window.IS_OWNER || false;
      const accessType = window.CART_ACCESS_TYPE || "public";

      let confirmMsg = "Are you sure you want to leave this social cart?";

      if (isOwner) {
        if (accessType === "invite_only") {
          confirmMsg =
            "As the owner of this PRIVATE cart, if you leave:\n\n" +
            "• Ownership will transfer to the next member\n" +
            "• Your items will move to your personal cart\n" +
            "• The cart will remain active for other members\n\n" +
            "Continue?";
        } else {
          confirmMsg =
            "As the owner of this PUBLIC cart, if you leave:\n\n" +
            "⚠️ THE CART WILL BE CLOSED\n" +
            "⚠️ ALL MEMBERS WILL BE REMOVED\n" +
            "• Everyone's items will return to their personal carts\n\n" +
            "This action cannot be undone. Continue?";
        }
      }

      if (!confirm(confirmMsg)) return;

      if (!window.LEAVE_CART_URL) {
        return window.showToast("LEAVE_CART_URL missing", "error");
      }

      try {
        leaveBtn.disabled = true;
        leaveBtn.innerHTML =
          '<span class="spinner-border spinner-border-sm me-2"></span>Leaving...';

        const r = await postForm(window.LEAVE_CART_URL, {});
        if (!r.success) throw new Error(r.message || "Could not leave cart");

        window.showToast(r.message || "You left the social cart ✅", "success");
        setTimeout(() => window.location.reload(), 500);
      } catch (e) {
        window.showToast(e.message || "Could not leave cart", "error");
      } finally {
        leaveBtn.disabled = false;
        leaveBtn.innerHTML =
          '<i class="fas fa-sign-out-alt me-2"></i>Leave Cart';
      }
    });
  }

  // Leave & Checkout All Button (Owner only)
  if (checkoutBtn) {
    safeBind(checkoutBtn, "boundCheckoutAll", async () => {
      if (
        !confirm(
          "This will create orders for ALL members and close the social cart. Continue?"
        )
      ) {
        return;
      }

      if (!window.LEAVE_AND_CHECKOUT_URL) {
        return window.showToast("LEAVE_AND_CHECKOUT_URL missing", "error");
      }

      try {
        checkoutBtn.disabled = true;
        checkoutBtn.innerHTML =
          '<span class="spinner-border spinner-border-sm me-2"></span>Creating orders...';

        const r = await postForm(window.LEAVE_AND_CHECKOUT_URL, {});
        if (!r.success) throw new Error(r.message || "Could not create orders");

        window.showToast(r.message || "Orders created successfully ✅", "success");

        if (r.redirect_url) {
          setTimeout(() => (window.location.href = r.redirect_url), 1000);
        } else {
          setTimeout(() => window.location.reload(), 1000);
        }
      } catch (e) {
        window.showToast(e.message || "Could not create orders", "error");
      } finally {
        checkoutBtn.disabled = false;
        checkoutBtn.innerHTML =
          '<i class="fas fa-shopping-cart me-2"></i>Leave & Checkout All';
      }
    });
  }
}


  // =========================
  // CART ITEM OPERATIONS
  // =========================
  
  function moveItemToCart(itemId, targetCartType) {
    const csrftoken = getCSRFToken();
    
    fetch(window.MOVE_CART_ITEM_URL || '/cart/move-item/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrftoken,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: `item_id=${itemId}&target_cart_type=${targetCartType}`
    })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        window.showToast(`Item moved to ${targetCartType} cart`, 'success');
        setTimeout(() => location.reload(), 500);
      } else {
        window.showToast(data.message || 'Error moving item', 'error');
      }
    })
    .catch(err => {
      console.error('Error:', err);
      window.showToast('Failed to move item', 'error');
    });
  }

  function updateQuantity(itemId, quantity) {
    const csrftoken = getCSRFToken();
    
    fetch(window.UPDATE_CART_QUANTITY_URL || '/update-cart-quantity/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrftoken,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: `cart_item_id=${itemId}&quantity=${quantity}`
    })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        location.reload();
      } else {
        window.showToast(data.message || 'Error updating quantity', 'error');
      }
    });
  }

  function removeItem(itemId) {
    const csrftoken = getCSRFToken();
    
    fetch(window.REMOVE_CART_ITEM_URL || '/remove-cart-item/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrftoken,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: `item_id=${itemId}`
    })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        window.showToast('Item removed', 'success');
        location.reload();
      } else {
        window.showToast(data.message || 'Error removing item', 'error');
      }
    });
  }

  function bindCartItemControls() {
    // Quantity buttons
    document.querySelectorAll('.quantity-btn').forEach(btn => {
      if (btn.dataset.boundQty === "1") return;
      btn.dataset.boundQty = "1";
      
      btn.addEventListener('click', function() {
        const action = this.dataset.action;
        const itemId = this.dataset.itemId;
        const input = this.parentElement.querySelector('.quantity-input');
        let quantity = parseInt(input.value || "1", 10);

        if (action === 'increase') quantity += 1;
        else if (action === 'decrease' && quantity > 1) quantity -= 1;

        updateQuantity(itemId, quantity);
      });
    });

    // Quantity inputs
    document.querySelectorAll('.quantity-input').forEach(input => {
      if (input.dataset.boundQty === "1") return;
      input.dataset.boundQty = "1";
      
      input.addEventListener('change', function() {
        const itemId = this.dataset.itemId;
        let quantity = parseInt(this.value || "1", 10);
        if (quantity < 1) quantity = 1;
        updateQuantity(itemId, quantity);
      });
    });

    // Remove buttons
    document.querySelectorAll('.remove-item').forEach(btn => {
      if (btn.dataset.boundRemove === "1") return;
      btn.dataset.boundRemove = "1";
      
      btn.addEventListener('click', function() {
        if (!confirm('Remove this item from cart?')) return;
        removeItem(this.dataset.itemId);
      });
    });

    // Move to social buttons
    document.querySelectorAll('.move-to-social').forEach(btn => {
      if (btn.dataset.boundMove === "1") return;
      btn.dataset.boundMove = "1";
      
      btn.addEventListener('click', function() {
        moveItemToCart(this.dataset.itemId, 'social');
      });
    });

    // Move to normal buttons
    document.querySelectorAll('.move-to-normal').forEach(btn => {
      if (btn.dataset.boundMove === "1") return;
      btn.dataset.boundMove = "1";
      
      btn.addEventListener('click', function() {
        moveItemToCart(this.dataset.itemId, 'normal');
      });
    });
  }

  // =========================
  // DRAG AND DROP
  // =========================
  
  let draggedElement = null;

  window.handleDragStart = function(e) {
    draggedElement = e.target;
    e.target.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/html', e.target.innerHTML);
  };

  window.handleDragEnd = function(e) {
    e.target.classList.remove('dragging');
  };

  function bindDropZones() {
    const dropZones = document.querySelectorAll('.drop-zone');
    dropZones.forEach(zone => {
      if (zone.dataset.boundDrop === "1") return;
      zone.dataset.boundDrop = "1";
      
      zone.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        this.classList.add('drag-over');
      });

      zone.addEventListener('dragleave', function(e) {
        this.classList.remove('drag-over');
      });

      zone.addEventListener('drop', function(e) {
        e.preventDefault();
        this.classList.remove('drag-over');

        if (draggedElement) {
          const itemId = draggedElement.dataset.itemId;
          const targetCartType = this.dataset.cartType;
          const currentCartType = draggedElement.dataset.cartType;

          if (targetCartType !== currentCartType) {
            moveItemToCart(itemId, targetCartType);
          }
        }
      });
    });
  }

  // =========================
  // SPLIT MODE
  // =========================
  
  function bindSplitMode() {
    const saveSplitBtn = document.getElementById('saveSplitMode');
    if (!saveSplitBtn) return;
    
    safeBind(saveSplitBtn, "boundSplit", async () => {
      const splitMode = document.querySelector('input[name="splitMode"]:checked')?.value;
      if (!splitMode) return window.showToast("Please select a split mode", "error");

      const csrftoken = getCSRFToken();
      
      try {
        const res = await fetch(window.SET_SPLIT_MODE_URL || '/cart/split/set/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrftoken,
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: `split_mode=${splitMode}`
        });
        
        const data = await res.json();
        if (data.success) {
          window.showToast('Split mode updated!', 'success');
          const modal = bootstrap.Modal.getInstance(document.getElementById('splitModeModal'));
          if (modal) modal.hide();
          setTimeout(() => location.reload(), 1000);
        } else {
          window.showToast(data.message || 'Error updating split mode', 'error');
        }
      } catch (err) {
        window.showToast('Failed to update split mode', 'error');
      }
    });
  }

  // =========================
  // SHARE FUNCTIONS
  // =========================
  
  window.copyInviteCode = function() {
    const code = document.getElementById('inviteCode')?.textContent;
    if (!code) return;
    
    navigator.clipboard.writeText(code).then(() => {
      window.showToast('Invite code copied!', 'success');
    });
  };

  window.copyShareLink = function() {
    const link = document.getElementById('shareCartLink');
    if (!link) return;
    
    link.select();
    navigator.clipboard.writeText(link.value).then(() => {
      window.showToast('Link copied to clipboard!', 'success');
    });
  };

  window.copySocialLink = function() {
    const link = document.getElementById('socialInviteLink');
    if (!link) return;
    
    link.select();
    navigator.clipboard.writeText(link.value).then(() => {
      window.showToast('Invite link copied!', 'success');
    });
  };

  function bindShareButtons() {
    const shareInviteBtn = document.getElementById('shareInviteBtn');
    if (shareInviteBtn) {
      safeBind(shareInviteBtn, "boundShare", () => {
        const inviteLink = document.getElementById('socialInviteLink')?.value;
        if (!inviteLink) return;

        if (navigator.share) {
          navigator.share({
            title: 'Join my Social Cart',
            text: 'Shop together with me!',
            url: inviteLink
          });
        } else {
          navigator.clipboard.writeText(inviteLink);
          window.showToast('Invite link copied!', 'success');
        }
      });
    }
  }

  // =========================
  // SOCIAL CART LIVE CHAT
  // =========================
  
  let chatTimer = null;
  let inChatRefresh = false;

  window.currentChatScope = window.currentChatScope || "group";
  window.currentChatProductId = window.currentChatProductId || null;

  function isNearBottom(el, thresholdPx = 80) {
    const distance = el.scrollHeight - (el.scrollTop + el.clientHeight);
    return distance <= thresholdPx;
  }

  function insertAtCursor(input, text) {
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    const before = input.value.slice(0, start);
    const after = input.value.slice(end);
    input.value = before + text + after;
    const newPos = start + text.length;
    input.setSelectionRange(newPos, newPos);
    input.focus();
  }

  function setChatContext(scope, productId = null) {
    window.currentChatScope = scope || "group";
    window.currentChatProductId = productId ? String(productId) : null;

    const input = document.getElementById("socialChatInput");
    if (input) {
      if (scope === "group") input.placeholder = "Message cart members...";
      else if (scope === "item") input.placeholder = "Discuss this item with members...";
      else if (scope === "seller_item") input.placeholder = "Ask the shop owner about this item...";
    }
  }

  function buildChatFragmentURL() {
    const base = window.SOCIAL_CHAT_FRAGMENT_URL;
    if (!base) return null;

    const url = new URL(base, window.location.origin);
    url.searchParams.set("scope", window.currentChatScope || "group");

    if ((window.currentChatScope === "item" || window.currentChatScope === "seller_item") && window.currentChatProductId) {
      url.searchParams.set("product_id", String(window.currentChatProductId));
    }
    return url.toString();
  }

  async function refreshChatMessages({ silent = true } = {}) {
    const wrap = document.getElementById("socialChatMessages");
    const inner = document.getElementById("socialChatMessagesInner");
    if (!wrap || !inner) return;

    const url = buildChatFragmentURL();
    if (!url || inChatRefresh) return;

    inChatRefresh = true;

    const wasNearBottom = isNearBottom(wrap);
    const oldScrollTop = wrap.scrollTop;
    const oldScrollHeight = wrap.scrollHeight;

    try {
      const res = await fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });

      const html = await res.text();
      inner.innerHTML = html;

      bindThreadButtons();

      const newScrollHeight = wrap.scrollHeight;
      if (wasNearBottom) {
        wrap.scrollTop = wrap.scrollHeight;
      } else {
        const delta = newScrollHeight - oldScrollHeight;
        wrap.scrollTop = oldScrollTop + delta;
      }
    } catch (e) {
      if (!silent) console.warn("Chat refresh failed", e);
    } finally {
      inChatRefresh = false;
    }
  }

  async function sendChatMessage(text) {
    if (!window.SOCIAL_CHAT_SEND_URL) return;

    const body = new URLSearchParams();
    body.append("message", text);
    body.append("scope", window.currentChatScope || "group");

    if ((window.currentChatScope === "item" || window.currentChatScope === "seller_item") && window.currentChatProductId) {
      body.append("product_id", String(window.currentChatProductId));
    }

    const res = await fetch(window.SOCIAL_CHAT_SEND_URL, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCSRFToken(),
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: body.toString(),
      credentials: "same-origin",
    });

    const data = await res.json().catch(() => null);
    if (!data || !data.success) {
      throw new Error((data && data.message) || "Failed to send message");
    }
  }

  async function shareProductToGroupChat(productId) {
    if (!window.SOCIAL_CHAT_SEND_URL) return;

    const body = new URLSearchParams();
    body.append("scope", "group");
    body.append("attach_product", "1");
    body.append("product_id", String(productId));
    body.append("message", "");

    const res = await fetch(window.SOCIAL_CHAT_SEND_URL, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCSRFToken(),
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: body.toString(),
      credentials: "same-origin",
    });

    const data = await res.json().catch(() => null);
    if (!data || !data.success) {
      throw new Error((data && data.message) || "Failed to share item");
    }
  }

  function bindEmojiBar() {
    const input = document.getElementById("socialChatInput");
    const bar = document.getElementById("emojiBar");
    if (!input || !bar || bar.dataset.boundEmoji === "1") return;
    
    bar.dataset.boundEmoji = "1";

    bar.querySelectorAll(".emoji-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        insertAtCursor(input, btn.textContent || "");
      });
    });
  }

  function bindChatForm() {
    const form = document.getElementById("socialChatForm");
    const input = document.getElementById("socialChatInput");
    if (!form || !input || form.dataset.boundChat === "1") return;
    
    form.dataset.boundChat = "1";

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = (input.value || "").trim();
      if (!msg) return;

      input.value = "";
      try {
        await sendChatMessage(msg);
        await refreshChatMessages({ silent: true });
        
        const wrap = document.getElementById("socialChatMessages");
        if (wrap) wrap.scrollTop = wrap.scrollHeight;
      } catch (err) {
        window.showToast(err.message || "Chat error", "error");
      }
    });
  }

  function bindOwnerLiveToggle() {
    const btn = document.getElementById("ownerLiveToggleBtn");
    if (!btn || !window.SOCIAL_CART_SET_LIVE_URL) return;

    safeBind(btn, "boundLive", async () => {
      const label = document.getElementById("ownerLiveLabel");
      const currentlyLive = label && label.textContent.trim().toLowerCase() === "live";
      const newVal = !currentlyLive;

      const body = new URLSearchParams();
      body.append("is_live", newVal ? "true" : "false");

      try {
        const res = await fetch(window.SOCIAL_CART_SET_LIVE_URL, {
          method: "POST",
          headers: {
            "X-CSRFToken": getCSRFToken(),
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
          },
          body: body.toString(),
          credentials: "same-origin",
        });

        const data = await res.json().catch(() => null);
        if (!data || !data.success) {
          throw new Error((data && data.message) || "Failed to update live status");
        }

        if (label) label.textContent = data.is_live ? "Live" : "Go Live";
        window.showToast(data.is_live ? "You are LIVE ✅" : "You are offline", "success");
      } catch (e) {
        window.showToast(e.message || "Error", "error");
      }
    });
  }

  function bindThreadButtons() {
    const root = document.getElementById("socialChatMessagesInner");
    if (!root) return;

    root.querySelectorAll(".ask-seller").forEach(btn => {
      if (btn.dataset.boundThread === "1") return;
      btn.dataset.boundThread = "1";

      btn.addEventListener("click", async () => {
        const productId = btn.getAttribute("data-product-id");
        if (!productId) return;

        setChatContext("seller_item", productId);
        await refreshChatMessages({ silent: true });

        const wrap = document.getElementById("socialChatMessages");
        if (wrap) wrap.scrollTop = wrap.scrollHeight;
      });
    });

    root.querySelectorAll(".open-item-thread").forEach(btn => {
      if (btn.dataset.boundThread === "1") return;
      btn.dataset.boundThread = "1";

      btn.addEventListener("click", async () => {
        const productId = btn.getAttribute("data-product-id");
        if (!productId) return;

        setChatContext("item", productId);
        await refreshChatMessages({ silent: true });

        const wrap = document.getElementById("socialChatMessages");
        if (wrap) wrap.scrollTop = wrap.scrollHeight;
      });
    });
  }

  function bindAddChatProductButtons() {
  const root = document.getElementById("socialChatMessagesInner");
  if (!root) return;

  root.querySelectorAll(".add-chat-product").forEach(btn => {
    if (btn.dataset.boundAddChat === "1") return;
    btn.dataset.boundAddChat = "1";

    btn.addEventListener("click", async () => {
      const productId = btn.getAttribute("data-product-id");
      const qty = parseInt(btn.getAttribute("data-qty") || "1", 10);

      let features = {};
      try {
        features = JSON.parse(btn.getAttribute("data-features") || "{}");
      } catch (e) {
        features = {};
      }

      if (!window.ADD_TO_CART_FROM_CHAT_URL) {
        return window.showToast("ADD_TO_CART_FROM_CHAT_URL missing", "error");
      }

      try {
        btn.disabled = true;
        const old = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Adding...';

        const res = await fetch(window.ADD_TO_CART_FROM_CHAT_URL, {
          method: "POST",
          headers: {
            "X-CSRFToken": getCSRFToken(),
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
          },
          body: JSON.stringify({
            product_id: productId,
            quantity: qty,
            selected_features: features,
            target_cart: "personal"   // or "social" if you prefer
          }),
          credentials: "same-origin",
        });

        const data = await res.json().catch(() => null);
        if (!data || !data.success) throw new Error((data && data.message) || "Failed to add to cart");

        window.showToast("Added to cart ✅", "success");
        // optional: update cart count badge if you have one
      } catch (e) {
        window.showToast(e.message || "Error", "error");
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-cart-plus me-1"></i>Add to Cart';
      }
    });
  });
}


  function bindShareToChatButtons() {
    document.querySelectorAll(".share-to-chat").forEach(btn => {
      if (btn.dataset.boundShareChat === "1") return;
      btn.dataset.boundShareChat = "1";

      btn.addEventListener("click", async () => {
        const productId = btn.getAttribute("data-product-id");
        if (!productId) return;

        try {
          await shareProductToGroupChat(productId);

          setChatContext("group", null);
          await refreshChatMessages({ silent: true });

          const wrap = document.getElementById("socialChatMessages");
          if (wrap) wrap.scrollTop = wrap.scrollHeight;

          window.showToast("Item shared to chat ✅", "success");
        } catch (e) {
          window.showToast(e.message || "Error", "error");
        }
      });
    });
  }

  window.socialChatGoGroup = async function () {
    setChatContext("group", null);
    await refreshChatMessages({ silent: true });
    const wrap = document.getElementById("socialChatMessages");
    if (wrap) wrap.scrollTop = wrap.scrollHeight;
  };

  function startChatPolling() {
    if (chatTimer) clearInterval(chatTimer);

    refreshChatMessages({ silent: true }).then(() => {
      const wrap = document.getElementById("socialChatMessages");
      if (wrap) wrap.scrollTop = wrap.scrollHeight;
    });

    chatTimer = setInterval(() => {
      refreshChatMessages({ silent: true });
    }, 2000);

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) refreshChatMessages({ silent: true });
    });
  }

  // =========================
  // TOOLTIPS
  // =========================
  
  function initTooltips() {
    const tooltipTriggerList = [].slice.call(
      document.querySelectorAll('[data-bs-toggle="tooltip"]')
    );
    tooltipTriggerList.forEach(function (tooltipTriggerEl) {
      new bootstrap.Tooltip(tooltipTriggerEl);
    });
  }

  // =========================
  // INITIALIZATION
  // =========================
  
  function init() {
    // Core functionality
    bindStartSocialCartButton();
    bindStartSocialCartModal();
    bindManageMembersModal();
    bindLeaveCart();
    bindCartItemControls();
    bindDropZones();
    bindSplitMode();
    bindShareButtons();
    
    // Chat functionality (only if social cart is active)
    if (window.IS_SOCIAL_ACTIVE) {
      bindEmojiBar();
      bindChatForm();
      bindOwnerLiveToggle();
      bindShareToChatButtons();
      startChatPolling();
    }
    
    // UI enhancements
    initTooltips();
    
    // Touch device detection
    if ('ontouchstart' in window) {
      document.body.classList.add('touch-device');
    }
  }

  // Expose refreshMemberPanel globally
  window.refreshMemberPanel = refreshMembersPanel;

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
