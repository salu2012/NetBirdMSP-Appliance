/**
 * NetBird MSP Appliance - Frontend Application
 * Vanilla JavaScript with Bootstrap 5
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let authToken = localStorage.getItem('authToken') || null;
let currentUser = null;
let currentPage = 'dashboard';
let currentCustomerId = null;
let currentCustomerData = null;
let customersPage = 1;
let brandingData = { branding_name: 'NetBird MSP Appliance', branding_logo_path: null };
let azureConfig = { azure_enabled: false };

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------
async function api(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (authToken) {
        opts.headers['Authorization'] = `Bearer ${authToken}`;
    }
    if (body) {
        opts.body = JSON.stringify(body);
    }
    let resp;
    try {
        resp = await fetch(`/api${path}`, opts);
    } catch (networkErr) {
        console.error(`API network error: ${method} ${path}`, networkErr);
        throw new Error(t('errors.networkError'));
    }
    if (resp.status === 401 && !path.startsWith('/auth/mfa/') && path !== '/auth/login') {
        logout();
        throw new Error(t('errors.sessionExpired'));
    }
    let data;
    try {
        data = await resp.json();
    } catch (jsonErr) {
        console.error(`API JSON parse error: ${method} ${path} (status ${resp.status})`, jsonErr);
        throw new Error(t('errors.serverError', { status: resp.status }));
    }
    if (!resp.ok) {
        let msg = t('errors.requestFailed');
        if (Array.isArray(data.detail)) {
            msg = data.detail.map(e => {
                const field = e.loc ? e.loc[e.loc.length - 1] : '';
                const text = (e.msg || '').replace(/^Value error, ?/, '');
                return field ? `${field}: ${text}` : text;
            }).join('\n');
        } else if (typeof data.detail === 'string') {
            msg = data.detail;
        } else if (data.message) {
            msg = data.message;
        }
        console.error(`API error: ${method} ${path} (status ${resp.status})`, msg);
        throw new Error(msg);
    }
    return data;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
async function initApp() {
    await initI18n();
    await loadBranding();
    await loadAzureLoginConfig();

    if (authToken) {
        try {
            const user = await api('GET', '/auth/me');
            currentUser = user;
            document.getElementById('nav-username').textContent = user.username;
            // Apply user's language preference if set
            if (user.default_language && !localStorage.getItem('language')) {
                await setLanguage(user.default_language);
            }
            showAppPage();
            loadDashboard();
        } catch {
            authToken = null;
            localStorage.removeItem('authToken');
            showLoginPage();
        }
    } else {
        showLoginPage();
    }
}

function showLoginPage() {
    document.getElementById('login-page').classList.remove('d-none');
    document.getElementById('app-page').classList.add('d-none');
    // Reset MFA sections when going back to login
    resetLoginForm();
}

function showAppPage() {
    document.getElementById('login-page').classList.add('d-none');
    document.getElementById('app-page').classList.remove('d-none');
}

async function loadBranding() {
    try {
        const resp = await fetch('/api/settings/branding');
        if (resp.ok) {
            brandingData = await resp.json();
            // Set system default language from server config
            if (brandingData.default_language) {
                setSystemDefault(brandingData.default_language);
            }
            applyBranding();
        }
    } catch {
        // Use defaults
    }
}

function applyBranding() {
    const name = brandingData.branding_name || 'NetBird MSP Appliance';
    const subtitle = brandingData.branding_subtitle || t('login.subtitle');
    const logoPath = brandingData.branding_logo_path;

    // Login page
    document.getElementById('login-title').textContent = name;
    const subtitleEl = document.getElementById('login-subtitle');
    if (subtitleEl) subtitleEl.textContent = subtitle;
    document.title = name;
    if (logoPath) {
        document.getElementById('login-logo').innerHTML = `<img src="${logoPath}" alt="Logo" style="max-height:64px;max-width:200px;" class="mb-1">`;
    } else {
        document.getElementById('login-logo').innerHTML = '<i class="bi bi-hdd-network fs-1 text-primary"></i>';
    }

    // Navbar — use short form for the nav bar
    const shortName = name.length > 30 ? name.substring(0, 30) + '\u2026' : name;
    document.getElementById('nav-brand-name').textContent = shortName;
    if (logoPath) {
        document.getElementById('nav-logo').innerHTML = `<img src="${logoPath}" alt="Logo" style="height:28px;max-width:120px;" class="me-2">`;
    } else {
        document.getElementById('nav-logo').innerHTML = '<i class="bi bi-hdd-network me-2"></i>';
    }
}

async function loadAzureLoginConfig() {
    try {
        const resp = await fetch('/api/auth/azure/config');
        if (resp.ok) {
            azureConfig = await resp.json();
            if (azureConfig.azure_enabled) {
                document.getElementById('azure-login-divider').classList.remove('d-none');
            } else {
                document.getElementById('azure-login-divider').classList.add('d-none');
            }
        }
    } catch {
        // Azure not configured
    }
}

function loginWithAzure() {
    if (!azureConfig.azure_enabled || !azureConfig.azure_tenant_id || !azureConfig.azure_client_id) {
        alert(t('errors.azureNotConfigured'));
        return;
    }
    const redirectUri = window.location.origin + '/';
    const authUrl = `https://login.microsoftonline.com/${azureConfig.azure_tenant_id}/oauth2/v2.0/authorize`
        + `?client_id=${azureConfig.azure_client_id}`
        + `&response_type=code`
        + `&redirect_uri=${encodeURIComponent(redirectUri)}`
        + `&scope=${encodeURIComponent('openid profile email User.Read')}`
        + `&response_mode=query`;
    window.location.href = authUrl;
}

async function handleAzureCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (!code) return false;

    // Clear URL params
    window.history.replaceState({}, document.title, '/');

    try {
        const data = await api('POST', '/auth/azure/callback', {
            code: code,
            redirect_uri: window.location.origin + '/',
        });
        authToken = data.access_token;
        localStorage.setItem('authToken', authToken);
        currentUser = data.user;
        document.getElementById('nav-username').textContent = currentUser.username;
        // Apply user's language preference
        if (currentUser.default_language) {
            await setLanguage(currentUser.default_language);
        }
        showAppPage();
        loadDashboard();
        return true;
    } catch (err) {
        const errorEl = document.getElementById('login-error');
        errorEl.textContent = t('errors.azureLoginFailed', { error: err.message });
        errorEl.classList.remove('d-none');
        showLoginPage();
        return true;
    }
}

// Track MFA token between login steps
let pendingMfaToken = null;

document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById('login-error');
    const spinner = document.getElementById('login-spinner');
    errorEl.classList.add('d-none');
    spinner.classList.remove('d-none');

    try {
        const data = await api('POST', '/auth/login', {
            username: document.getElementById('login-username').value,
            password: document.getElementById('login-password').value,
        });

        // Check if MFA is required
        if (data.mfa_required) {
            pendingMfaToken = data.mfa_token;
            document.getElementById('login-form').classList.add('d-none');
            document.getElementById('azure-login-divider').classList.add('d-none');

            if (data.totp_setup_needed) {
                // First-time TOTP setup — get QR code
                await startMfaSetup();
            } else {
                // Existing TOTP — show verify form
                document.getElementById('mfa-verify-section').classList.remove('d-none');
                document.getElementById('mfa-code').focus();
            }
            return;
        }

        // Normal login (no MFA)
        completeLogin(data);
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('d-none');
    } finally {
        spinner.classList.add('d-none');
    }
});

async function completeLogin(data) {
    authToken = data.access_token;
    localStorage.setItem('authToken', authToken);
    currentUser = data.user;
    document.getElementById('nav-username').textContent = currentUser.username;
    if (currentUser.default_language) {
        await setLanguage(currentUser.default_language);
    }
    pendingMfaToken = null;
    showAppPage();
    loadDashboard();
}

function resetLoginForm() {
    pendingMfaToken = null;
    document.getElementById('login-form').classList.remove('d-none');
    document.getElementById('mfa-verify-section').classList.add('d-none');
    document.getElementById('mfa-setup-section').classList.add('d-none');
    document.getElementById('login-error').classList.add('d-none');
    document.getElementById('login-password').value = '';
    // Re-check azure config visibility
    if (azureConfig.azure_enabled) {
        document.getElementById('azure-login-divider').classList.remove('d-none');
    }
}

// MFA Verify form (existing TOTP)
document.getElementById('mfa-verify-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById('mfa-verify-error');
    const spinner = document.getElementById('mfa-verify-spinner');
    errorEl.classList.add('d-none');
    spinner.classList.remove('d-none');

    try {
        const data = await api('POST', '/auth/mfa/verify', {
            mfa_token: pendingMfaToken,
            totp_code: document.getElementById('mfa-code').value,
        });
        completeLogin(data);
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('d-none');
        document.getElementById('mfa-code').value = '';
        document.getElementById('mfa-code').focus();
    } finally {
        spinner.classList.add('d-none');
    }
});

// MFA Setup — get QR code from server
async function startMfaSetup() {
    try {
        const data = await api('POST', '/auth/mfa/setup', {
            mfa_token: pendingMfaToken,
        });
        document.getElementById('mfa-qr-code').src = data.qr_code;
        document.getElementById('mfa-secret-manual').textContent = data.secret;
        document.getElementById('mfa-setup-section').classList.remove('d-none');
        document.getElementById('mfa-setup-code').focus();
    } catch (err) {
        document.getElementById('login-error').textContent = err.message;
        document.getElementById('login-error').classList.remove('d-none');
        resetLoginForm();
    }
}

// MFA Setup Complete form (first-time TOTP)
document.getElementById('mfa-setup-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById('mfa-setup-error');
    const spinner = document.getElementById('mfa-setup-spinner');
    errorEl.classList.add('d-none');
    spinner.classList.remove('d-none');

    try {
        const data = await api('POST', '/auth/mfa/setup/complete', {
            mfa_token: pendingMfaToken,
            totp_code: document.getElementById('mfa-setup-code').value,
        });
        completeLogin(data);
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('d-none');
        document.getElementById('mfa-setup-code').value = '';
        document.getElementById('mfa-setup-code').focus();
    } finally {
        spinner.classList.add('d-none');
    }
});

// Back-to-login links
document.getElementById('mfa-back-to-login').addEventListener('click', (e) => {
    e.preventDefault();
    resetLoginForm();
});
document.getElementById('mfa-setup-back-to-login').addEventListener('click', (e) => {
    e.preventDefault();
    resetLoginForm();
});

function logout() {
    // Use fetch directly (not api()) to avoid 401 → logout → 401 infinite loop
    if (authToken) {
        fetch('/api/auth/logout', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`,
            },
        }).catch(() => { });
    }
    authToken = null;
    currentUser = null;
    localStorage.removeItem('authToken');
    showLoginPage();
}

// ---------------------------------------------------------------------------
// Language switching (saves preference to server for logged-in users)
// ---------------------------------------------------------------------------
async function switchLanguage(lang) {
    await setLanguage(lang);
    applyBranding();
    // Save preference to server if user is logged in
    if (currentUser && currentUser.id) {
        try {
            await api('PUT', `/users/${currentUser.id}`, { default_language: lang });
            currentUser.default_language = lang;
        } catch {
            // Silently fail — localStorage already saved
        }
    }
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function showPage(page) {
    document.querySelectorAll('.page-content').forEach(el => el.classList.add('d-none'));
    document.getElementById(`page-${page}`).classList.remove('d-none');
    currentPage = page;

    if (page === 'dashboard') loadDashboard();
    else if (page === 'settings') loadSettings();
    else if (page === 'monitoring') loadMonitoring();
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadDashboard() {
    await Promise.all([loadStats(), loadCustomers()]);
}

async function loadStats() {
    try {
        const data = await api('GET', '/monitoring/status');
        document.getElementById('stat-total').textContent = data.total_customers;
        document.getElementById('stat-active').textContent = data.active;
        document.getElementById('stat-inactive').textContent = data.inactive;
        document.getElementById('stat-error').textContent = data.error;
    } catch (err) {
        console.error('Failed to load stats:', err);
    }
}

async function loadCustomers() {
    const search = document.getElementById('search-input').value;
    const status = document.getElementById('status-filter').value;
    let url = `/customers?page=${customersPage}&per_page=25`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;

    try {
        const data = await api('GET', url);
        renderCustomersTable(data);
    } catch (err) {
        console.error('Failed to load customers:', err);
    }
}

function renderCustomersTable(data) {
    const tbody = document.getElementById('customers-table-body');
    if (!data.items || data.items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">${t('dashboard.noCustomers')}</td></tr>`;
        document.getElementById('pagination-info').textContent = t('dashboard.showingEmpty');
        document.getElementById('pagination-controls').innerHTML = '';
        return;
    }

    tbody.innerHTML = data.items.map(c => {
        const dPort = c.deployment && c.deployment.dashboard_port;
        const dashUrl = c.deployment && c.deployment.setup_url;
        const dashLink = dPort
            ? `<a href="${esc(dashUrl || 'http://localhost:' + dPort)}" target="_blank" class="text-decoration-none" title="${t('customer.openDashboard')}">:${dPort} <i class="bi bi-box-arrow-up-right"></i></a>`
            : '-';
        return `<tr>
            <td>${c.id}</td>
            <td><a href="#" onclick="viewCustomer(${c.id})" class="text-decoration-none fw-semibold">${esc(c.name)}</a></td>
            <td><code>${esc(c.subdomain)}</code></td>
            <td>${statusBadge(c.status)}</td>
            <td>${dashLink}</td>
            <td>${c.max_devices}</td>
            <td>${formatDate(c.created_at)}</td>
            <td>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" title="${t('common.view')}" onclick="viewCustomer(${c.id})"><i class="bi bi-eye"></i></button>
                    ${c.deployment && c.deployment.deployment_status === 'running'
                ? `<button class="btn btn-outline-warning" title="${t('common.stop')}" onclick="customerAction(${c.id},'stop')"><i class="bi bi-stop-circle"></i></button>`
                : `<button class="btn btn-outline-success" title="${t('common.start')}" onclick="customerAction(${c.id},'start')"><i class="bi bi-play-circle"></i></button>`
            }
                    <button class="btn btn-outline-info" title="${t('common.restart')}" onclick="customerAction(${c.id},'restart')"><i class="bi bi-arrow-repeat"></i></button>
                    <button class="btn btn-outline-danger" title="${t('common.delete')}" onclick="showDeleteModal(${c.id},'${esc(c.name)}')"><i class="bi bi-trash"></i></button>
                </div>
            </td>
        </tr>`;
    }).join('');

    // Pagination
    const start = (data.page - 1) * data.per_page + 1;
    const end = Math.min(data.page * data.per_page, data.total);
    document.getElementById('pagination-info').textContent = t('dashboard.showing', { start, end, total: data.total });

    let paginationHtml = '';
    for (let i = 1; i <= data.pages; i++) {
        paginationHtml += `<li class="page-item ${i === data.page ? 'active' : ''}"><a class="page-link" href="#" onclick="goToPage(${i})">${i}</a></li>`;
    }
    document.getElementById('pagination-controls').innerHTML = paginationHtml;
}

function goToPage(page) {
    customersPage = page;
    loadCustomers();
}

// Search & filter listeners
document.getElementById('search-input').addEventListener('input', debounce(() => { customersPage = 1; loadCustomers(); }, 300));
document.getElementById('status-filter').addEventListener('change', () => { customersPage = 1; loadCustomers(); });

// ---------------------------------------------------------------------------
// Customer CRUD
// ---------------------------------------------------------------------------
function showNewCustomerModal() {
    document.getElementById('customer-modal-title').textContent = t('customerModal.newCustomer');
    document.getElementById('customer-edit-id').value = '';
    document.getElementById('customer-form').reset();
    document.getElementById('cust-max-devices').value = '20';
    document.getElementById('customer-modal-error').classList.add('d-none');
    const saveBtnSpan = document.getElementById('customer-save-btn').querySelector('span[data-i18n]');
    if (saveBtnSpan) saveBtnSpan.textContent = t('customerModal.saveAndDeploy');

    // Update subdomain suffix
    api('GET', '/settings/system').then(cfg => {
        document.getElementById('cust-subdomain-suffix').textContent = `.${cfg.base_domain || 'domain.com'}`;
    }).catch(() => { });

    const modalEl = document.getElementById('customer-modal');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    // Enable subdomain field for new customers
    document.getElementById('cust-subdomain').disabled = false;
    modal.show();
}

function editCurrentCustomer() {
    if (!currentCustomerData) return;
    const c = currentCustomerData;
    document.getElementById('customer-modal-title').textContent = t('customerModal.editCustomer');
    document.getElementById('customer-edit-id').value = c.id;
    document.getElementById('cust-name').value = c.name;
    document.getElementById('cust-company').value = c.company || '';
    document.getElementById('cust-subdomain').value = c.subdomain;
    document.getElementById('cust-subdomain').disabled = true; // Can't change subdomain
    document.getElementById('cust-email').value = c.email;
    document.getElementById('cust-max-devices').value = c.max_devices;
    document.getElementById('cust-notes').value = c.notes || '';
    document.getElementById('customer-modal-error').classList.add('d-none');
    const saveBtnSpan = document.getElementById('customer-save-btn').querySelector('span[data-i18n]');
    if (saveBtnSpan) saveBtnSpan.textContent = t('customerModal.saveChanges');

    const modalEl = document.getElementById('customer-modal');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
}

async function saveCustomer() {
    const errorEl = document.getElementById('customer-modal-error');
    const spinner = document.getElementById('customer-save-spinner');
    errorEl.classList.add('d-none');
    spinner.classList.remove('d-none');

    const editId = document.getElementById('customer-edit-id').value;
    const payload = {
        name: document.getElementById('cust-name').value,
        company: document.getElementById('cust-company').value || null,
        email: document.getElementById('cust-email').value,
        max_devices: parseInt(document.getElementById('cust-max-devices').value) || 20,
        notes: document.getElementById('cust-notes').value || null,
    };

    try {
        if (editId) {
            await api('PUT', `/customers/${editId}`, payload);
        } else {
            payload.subdomain = document.getElementById('cust-subdomain').value.toLowerCase();
            await api('POST', '/customers', payload);
        }
        // Close modal safely
        const modalEl = document.getElementById('customer-modal');
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) {
            modalInstance.hide();
        } else {
            modalEl.classList.remove('show');
            document.body.classList.remove('modal-open');
            document.querySelector('.modal-backdrop')?.remove();
        }
        loadDashboard();
        if (editId && currentCustomerId == editId) {
            viewCustomer(editId);
        }
    } catch (err) {
        console.error('saveCustomer error:', err);
        errorEl.textContent = err.message || t('errors.unknownError');
        errorEl.classList.remove('d-none');
        errorEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } finally {
        spinner.classList.add('d-none');
    }
}

function showDeleteModal(id, name) {
    document.getElementById('delete-customer-id').value = id;
    document.getElementById('delete-customer-name').textContent = name;
    new bootstrap.Modal(document.getElementById('delete-modal')).show();
}

function deleteCurrentCustomer() {
    if (!currentCustomerData) return;
    showDeleteModal(currentCustomerData.id, currentCustomerData.name);
}

async function confirmDeleteCustomer() {
    const id = document.getElementById('delete-customer-id').value;
    const spinner = document.getElementById('delete-spinner');
    spinner.classList.remove('d-none');

    try {
        await api('DELETE', `/customers/${id}`);
        bootstrap.Modal.getInstance(document.getElementById('delete-modal')).hide();
        showPage('dashboard');
    } catch (err) {
        alert(t('errors.deleteFailed', { error: err.message }));
    } finally {
        spinner.classList.add('d-none');
    }
}

// ---------------------------------------------------------------------------
// Customer Actions (start/stop/restart)
// ---------------------------------------------------------------------------
async function customerAction(id, action) {
    try {
        await api('POST', `/customers/${id}/${action}`);
        if (currentPage === 'dashboard') loadCustomers();
        if (currentCustomerId == id) viewCustomer(id);
    } catch (err) {
        alert(t('errors.actionFailed', { action, error: err.message }));
    }
}

// ---------------------------------------------------------------------------
// Customer Detail
// ---------------------------------------------------------------------------
async function viewCustomer(id) {
    currentCustomerId = id;
    showPage('customer-detail');

    try {
        const data = await api('GET', `/customers/${id}`);
        currentCustomerData = data;
        document.getElementById('detail-customer-name').textContent = data.name;
        const badge = document.getElementById('detail-customer-status');
        badge.innerHTML = statusBadge(data.status);

        // Info tab
        document.getElementById('detail-info-content').innerHTML = `
            <div class="row g-3">
                <div class="col-md-6"><strong>${t('customer.name')}</strong> ${esc(data.name)}</div>
                <div class="col-md-6"><strong>${t('customer.company')}</strong> ${esc(data.company || '-')}</div>
                <div class="col-md-6"><strong>${t('customer.subdomain')}</strong> <code>${esc(data.subdomain)}</code></div>
                <div class="col-md-6"><strong>${t('customer.email')}</strong> ${esc(data.email)}</div>
                <div class="col-md-6"><strong>${t('customer.maxDevices')}</strong> ${data.max_devices}</div>
                <div class="col-md-6"><strong>${t('customer.status')}</strong> ${statusBadge(data.status)}</div>
                <div class="col-md-6"><strong>${t('customer.created')}</strong> ${formatDate(data.created_at)}</div>
                <div class="col-md-6"><strong>${t('customer.updated')}</strong> ${formatDate(data.updated_at)}</div>
                ${data.notes ? `<div class="col-12"><strong>${t('customer.notes')}</strong> ${esc(data.notes)}</div>` : ''}
            </div>
        `;

        // Deployment tab
        if (data.deployment) {
            const d = data.deployment;
            document.getElementById('detail-deployment-content').innerHTML = `
                <div class="row g-3">
                    <div class="col-md-6"><strong>${t('customer.deploymentStatus')}</strong> ${statusBadge(d.deployment_status)}</div>
                    <div class="col-md-6"><strong>${t('customer.relayUdpPort')}</strong> ${d.relay_udp_port}</div>
                    <div class="col-md-6"><strong>${t('customer.dashboardPort')}</strong> ${d.dashboard_port || '-'}${d.dashboard_port ? ` <a href="${esc(d.setup_url || 'http://localhost:' + d.dashboard_port)}" target="_blank" class="ms-2"><i class="bi bi-box-arrow-up-right"></i> ${t('customer.open')}</a>` : ''}</div>
                    <div class="col-md-6"><strong>${t('customer.containerPrefix')}</strong> <code>${esc(d.container_prefix)}</code></div>
                    <div class="col-md-6"><strong>${t('customer.deployed')}</strong> ${formatDate(d.deployed_at)}</div>
                    <div class="col-12">
                        <strong>${t('customer.setupUrl')}</strong>
                        <div class="input-group mt-1">
                            <input type="text" class="form-control" value="${esc(d.setup_url || '')}" readonly id="setup-url-input">
                            <button class="btn btn-outline-secondary" onclick="copySetupUrl()"><i class="bi bi-clipboard"></i> ${t('customer.copy')}</button>
                        </div>
                    </div>
                </div>
                <div class="card mt-3">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <strong><i class="bi bi-key me-1"></i>${t('customer.netbirdLogin')}</strong>
                        ${d.has_credentials ? '' : `<span class="badge bg-secondary">${t('customer.notAvailable')}</span>`}
                    </div>
                    <div class="card-body" id="credentials-container">
                        ${d.has_credentials ? `
                        <div id="credentials-placeholder">
                            <button class="btn btn-outline-primary btn-sm" onclick="loadCredentials(${id})">
                                <i class="bi bi-shield-lock me-1"></i>${t('customer.showCredentials')}
                            </button>
                        </div>
                        <div id="credentials-content" style="display:none">
                            <div class="mb-2">
                                <label class="form-label mb-1"><small>${t('customer.credEmail')}</small></label>
                                <div class="input-group input-group-sm">
                                    <input type="text" class="form-control" id="cred-email" readonly>
                                    <button class="btn btn-outline-secondary" onclick="copyCredential('cred-email')" title="${t('customer.copy')}"><i class="bi bi-clipboard"></i></button>
                                </div>
                            </div>
                            <div>
                                <label class="form-label mb-1"><small>${t('customer.credPassword')}</small></label>
                                <div class="input-group input-group-sm">
                                    <input type="password" class="form-control" id="cred-password" readonly>
                                    <button class="btn btn-outline-secondary" data-toggle-pw onclick="togglePasswordVisibility('cred-password')" title="${t('customer.showHide')}"><i class="bi bi-eye"></i></button>
                                    <button class="btn btn-outline-secondary" onclick="copyCredential('cred-password')" title="${t('customer.copy')}"><i class="bi bi-clipboard"></i></button>
                                </div>
                            </div>
                        </div>
                        ` : `<p class="text-muted mb-0">${t('customer.credentialsNotAvailable')}</p>`}
                    </div>
                </div>
                <div class="mt-3">
                    <button class="btn btn-success btn-sm me-1" onclick="customerAction(${id},'start')"><i class="bi bi-play-circle me-1"></i>${t('customer.start')}</button>
                    <button class="btn btn-warning btn-sm me-1" onclick="customerAction(${id},'stop')"><i class="bi bi-stop-circle me-1"></i>${t('customer.stop')}</button>
                    <button class="btn btn-info btn-sm me-1" onclick="customerAction(${id},'restart')"><i class="bi bi-arrow-repeat me-1"></i>${t('customer.restart')}</button>
                    <button class="btn btn-outline-primary btn-sm" onclick="customerAction(${id},'deploy')"><i class="bi bi-rocket me-1"></i>${t('customer.reDeploy')}</button>
                </div>
            `;
        } else {
            document.getElementById('detail-deployment-content').innerHTML = `
                <p class="text-muted">${t('customer.noDeployment')}</p>
                <button class="btn btn-primary" onclick="customerAction(${id},'deploy')"><i class="bi bi-rocket me-1"></i>${t('customer.deployNow')}</button>
            `;
        }

        // Logs tab (preview from deployment_logs table)
        if (data.logs && data.logs.length > 0) {
            document.getElementById('detail-logs-content').innerHTML = data.logs.map(l =>
                `<div class="log-entry log-${l.status}"><span class="log-time">${formatDate(l.created_at)}</span> <span class="badge bg-${l.status === 'success' ? 'success' : l.status === 'error' ? 'danger' : 'info'}">${l.status}</span> <strong>${esc(l.action)}</strong>: ${esc(l.message)}</div>`
            ).join('');
        }
    } catch (err) {
        document.getElementById('detail-info-content').innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

async function loadCustomerLogs() {
    if (!currentCustomerId) return;
    try {
        const data = await api('GET', `/customers/${currentCustomerId}/logs`);
        const content = document.getElementById('detail-logs-content');
        if (!data.logs || Object.keys(data.logs).length === 0) {
            content.innerHTML = `<p class="text-muted">${t('customer.noContainerLogs')}</p>`;
            return;
        }
        let html = '';
        for (const [name, logText] of Object.entries(data.logs)) {
            html += `<h6 class="mt-3"><i class="bi bi-box me-1"></i>${esc(name)}</h6><pre class="log-pre">${esc(logText)}</pre>`;
        }
        content.innerHTML = html;
    } catch (err) {
        document.getElementById('detail-logs-content').innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

async function loadCustomerHealth() {
    if (!currentCustomerId) return;
    try {
        const data = await api('GET', `/customers/${currentCustomerId}/health`);
        const content = document.getElementById('detail-health-content');
        let html = `<div class="mb-3"><strong>${t('customer.overall')}</strong> ${data.healthy ? `<span class="text-success">${t('customer.healthy')}</span>` : `<span class="text-danger">${t('customer.unhealthy')}</span>`}</div>`;
        if (data.containers && data.containers.length > 0) {
            html += `<table class="table table-sm"><thead><tr><th>${t('customer.thContainer')}</th><th>${t('customer.thContainerStatus')}</th><th>${t('customer.thHealth')}</th><th>${t('customer.thImage')}</th></tr></thead><tbody>`;
            data.containers.forEach(c => {
                const statusClass = c.status === 'running' ? 'text-success' : 'text-danger';
                const healthClass = c.health === 'healthy' ? 'text-success' : 'text-danger';
                const healthLabel = c.health === 'healthy' ? t('customer.healthy') : t('customer.unhealthy');
                html += `<tr><td>${esc(c.name)}</td><td class="${statusClass}">${c.status}</td><td class="${healthClass}">${healthLabel}</td><td><code>${esc(c.image)}</code></td></tr>`;
            });
            html += '</tbody></table>';
        }
        html += `<div class="text-muted small">${t('customer.lastCheck', { time: formatDate(data.last_check) })}</div>`;
        content.innerHTML = html;
    } catch (err) {
        document.getElementById('detail-health-content').innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

function copySetupUrl() {
    const input = document.getElementById('setup-url-input');
    navigator.clipboard.writeText(input.value).then(() => {
        showToast(t('messages.setupUrlCopied'));
    });
}

async function loadCredentials(customerId) {
    try {
        const data = await api('GET', `/customers/${customerId}/credentials`);
        document.getElementById('cred-email').value = data.email;
        document.getElementById('cred-password').value = data.password;
        document.getElementById('credentials-placeholder').style.display = 'none';
        document.getElementById('credentials-content').style.display = 'block';
    } catch (err) {
        showToast(t('errors.failedToLoadCredentials', { error: err.message }), 'danger');
    }
}

function copyCredential(fieldId) {
    const input = document.getElementById(fieldId);
    const origType = input.type;
    input.type = 'text';
    navigator.clipboard.writeText(input.value).then(() => {
        input.type = origType;
        showToast(t('messages.copiedToClipboard'));
    });
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
async function loadSettings() {
    try {
        const cfg = await api('GET', '/settings/system');
        document.getElementById('cfg-base-domain').value = cfg.base_domain || '';
        document.getElementById('cfg-admin-email').value = cfg.admin_email || '';
        document.getElementById('cfg-data-dir').value = cfg.data_dir || '';
        document.getElementById('cfg-docker-network').value = cfg.docker_network || '';
        document.getElementById('cfg-relay-base-port').value = cfg.relay_base_port || 3478;
        document.getElementById('cfg-dashboard-base-port').value = cfg.dashboard_base_port || 9000;
        document.getElementById('cfg-npm-api-url').value = cfg.npm_api_url || '';
        document.getElementById('npm-credentials-status').textContent = cfg.npm_credentials_set ? t('settings.credentialsSet') : t('settings.noCredentials');

        // SSL mode
        document.getElementById('cfg-ssl-mode').value = cfg.ssl_mode || 'letsencrypt';
        onSslModeChange();
        if (cfg.ssl_mode === 'wildcard') {
            loadNpmCertificates(cfg.wildcard_cert_id);
        }

        document.getElementById('cfg-mgmt-image').value = cfg.netbird_management_image || '';
        document.getElementById('cfg-signal-image').value = cfg.netbird_signal_image || '';
        document.getElementById('cfg-relay-image').value = cfg.netbird_relay_image || '';
        document.getElementById('cfg-dashboard-image').value = cfg.netbird_dashboard_image || '';

        // Branding tab
        document.getElementById('cfg-branding-name').value = cfg.branding_name || '';
        document.getElementById('cfg-branding-subtitle').value = cfg.branding_subtitle || '';
        document.getElementById('cfg-default-language').value = cfg.default_language || 'en';
        updateLogoPreview(cfg.branding_logo_path);

        // MFA tab (Security)
        document.getElementById('cfg-mfa-enabled').checked = cfg.mfa_enabled || false;
        loadMfaStatus();

        // Azure AD tab
        document.getElementById('cfg-azure-enabled').checked = cfg.azure_enabled || false;
        document.getElementById('cfg-azure-tenant').value = cfg.azure_tenant_id || '';
        document.getElementById('cfg-azure-client-id').value = cfg.azure_client_id || '';
        document.getElementById('azure-secret-status').textContent = cfg.azure_client_secret_set ? t('settings.secretSet') : t('settings.noSecret');
        document.getElementById('cfg-azure-group-id').value = cfg.azure_allowed_group_id || '';

        // DNS tab
        document.getElementById('cfg-dns-enabled').checked = cfg.dns_enabled || false;
        document.getElementById('cfg-dns-server').value = cfg.dns_server || '';
        document.getElementById('cfg-dns-zone').value = cfg.dns_zone || '';
        document.getElementById('cfg-dns-username').value = cfg.dns_username || '';
        document.getElementById('cfg-dns-record-ip').value = cfg.dns_record_ip || '';
        document.getElementById('dns-password-status').textContent = cfg.dns_password_set ? t('settings.passwordSet') : t('settings.noPasswordSet');

        // LDAP tab
        document.getElementById('cfg-ldap-enabled').checked = cfg.ldap_enabled || false;
        document.getElementById('cfg-ldap-server').value = cfg.ldap_server || '';
        document.getElementById('cfg-ldap-port').value = cfg.ldap_port || 389;
        document.getElementById('cfg-ldap-use-ssl').checked = cfg.ldap_use_ssl || false;
        document.getElementById('cfg-ldap-bind-dn').value = cfg.ldap_bind_dn || '';
        document.getElementById('cfg-ldap-base-dn').value = cfg.ldap_base_dn || '';
        document.getElementById('cfg-ldap-user-filter').value = cfg.ldap_user_filter || '(sAMAccountName={username})';
        document.getElementById('cfg-ldap-group-dn').value = cfg.ldap_group_dn || '';
        document.getElementById('ldap-password-status').textContent = cfg.ldap_bind_password_set ? t('settings.passwordSet') : t('settings.noPasswordSet');

        // Git/Update tab
        document.getElementById('cfg-git-repo-url').value = cfg.git_repo_url || '';
        document.getElementById('cfg-git-branch').value = cfg.git_branch || 'main';
        document.getElementById('git-token-status').textContent = cfg.git_token_set ? t('settings.tokenSet') : t('settings.noToken');
    } catch (err) {
        showSettingsAlert('danger', t('errors.failedToLoadSettings', { error: err.message }));
    }

    // Automatically fetch branches once the base config is populated
    await loadGitBranches();
}

function updateLogoPreview(logoPath) {
    const preview = document.getElementById('branding-logo-preview');
    if (logoPath) {
        preview.innerHTML = `<img src="${logoPath}" alt="Logo" style="max-height:64px;max-width:200px;"><div class="text-muted small mt-1">${logoPath}</div>`;
    } else {
        preview.innerHTML = `<i class="bi bi-hdd-network fs-1 text-primary"></i><div class="text-muted small mt-1">${t('settings.defaultIcon')}</div>`;
    }
}

// System settings form
document.getElementById('settings-system-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        await api('PUT', '/settings/system', {
            base_domain: document.getElementById('cfg-base-domain').value,
            admin_email: document.getElementById('cfg-admin-email').value,
            data_dir: document.getElementById('cfg-data-dir').value,
            docker_network: document.getElementById('cfg-docker-network').value,
            relay_base_port: parseInt(document.getElementById('cfg-relay-base-port').value),
            dashboard_base_port: parseInt(document.getElementById('cfg-dashboard-base-port').value),
        });
        showSettingsAlert('success', t('messages.systemSettingsSaved'));
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
});

// NPM settings form
document.getElementById('settings-npm-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = { npm_api_url: document.getElementById('cfg-npm-api-url').value };
    const email = document.getElementById('cfg-npm-api-email').value;
    const password = document.getElementById('cfg-npm-api-password').value;
    if (email) payload.npm_api_email = email;
    if (password) payload.npm_api_password = password;

    // SSL mode
    const sslMode = document.getElementById('cfg-ssl-mode').value;
    payload.ssl_mode = sslMode;
    if (sslMode === 'wildcard') {
        const certId = document.getElementById('cfg-wildcard-cert-id').value;
        if (certId) payload.wildcard_cert_id = parseInt(certId);
    }
    try {
        await api('PUT', '/settings/system', payload);
        showSettingsAlert('success', t('messages.npmSettingsSaved'));
        document.getElementById('cfg-npm-api-email').value = '';
        document.getElementById('cfg-npm-api-password').value = '';
        loadSettings();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
});

// Image settings form
document.getElementById('settings-images-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        await api('PUT', '/settings/system', {
            netbird_management_image: document.getElementById('cfg-mgmt-image').value,
            netbird_signal_image: document.getElementById('cfg-signal-image').value,
            netbird_relay_image: document.getElementById('cfg-relay-image').value,
            netbird_dashboard_image: document.getElementById('cfg-dashboard-image').value,
        });
        showSettingsAlert('success', t('messages.imageSettingsSaved'));
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
});

// Test NPM connection
async function testNpmConnection() {
    const spinner = document.getElementById('npm-test-spinner');
    const resultEl = document.getElementById('npm-test-result');
    spinner.classList.remove('d-none');
    resultEl.classList.add('d-none');

    try {
        const data = await api('GET', '/settings/test-npm');
        resultEl.className = `mt-3 alert alert-${data.ok ? 'success' : 'danger'}`;
        resultEl.textContent = data.message;
        resultEl.classList.remove('d-none');
    } catch (err) {
        resultEl.className = 'mt-3 alert alert-danger';
        resultEl.textContent = err.message;
        resultEl.classList.remove('d-none');
    } finally {
        spinner.classList.add('d-none');
    }
}

// SSL mode toggle
function onSslModeChange() {
    const mode = document.getElementById('cfg-ssl-mode').value;
    const section = document.getElementById('wildcard-cert-section');
    section.style.display = mode === 'wildcard' ? '' : 'none';
}

// Load NPM wildcard certificates into dropdown
async function loadNpmCertificates(preselectId) {
    const select = document.getElementById('cfg-wildcard-cert-id');
    const statusEl = document.getElementById('wildcard-cert-status');
    select.innerHTML = `<option value="">${t('settings.selectCertificate')}</option>`;
    statusEl.textContent = t('common.loading');
    statusEl.className = 'mt-1 text-muted';

    try {
        const certs = await api('GET', '/settings/npm-certificates');
        const wildcards = certs.filter(c => c.is_wildcard || (c.domain_names && c.domain_names.some(d => d.startsWith('*.'))));
        wildcards.forEach(c => {
            const domains = (c.domain_names || []).join(', ');
            const expires = c.expires_on ? ` (${t('settings.expiresOn')}: ${new Date(c.expires_on).toLocaleDateString()})` : '';
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = `${domains}${expires}`;
            select.appendChild(opt);
        });
        if (preselectId) select.value = preselectId;
        statusEl.textContent = t('settings.certsLoaded', { count: wildcards.length });
        statusEl.className = wildcards.length > 0 ? 'mt-1 text-success small' : 'mt-1 text-warning small';
        if (wildcards.length === 0) statusEl.textContent = t('settings.noWildcardCerts');
    } catch (err) {
        statusEl.textContent = t('errors.failed', { error: err.message });
        statusEl.className = 'mt-1 text-danger small';
    }
}

// Change password form
document.getElementById('change-password-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const resultEl = document.getElementById('password-result');
    const newPw = document.getElementById('pw-new').value;
    const confirmPw = document.getElementById('pw-confirm').value;

    if (newPw !== confirmPw) {
        resultEl.className = 'mt-3 alert alert-danger';
        resultEl.textContent = t('errors.passwordsDoNotMatch');
        resultEl.classList.remove('d-none');
        return;
    }

    try {
        await api('POST', '/auth/change-password', {
            current_password: document.getElementById('pw-current').value,
            new_password: newPw,
        });
        resultEl.className = 'mt-3 alert alert-success';
        resultEl.textContent = t('messages.passwordChanged');
        resultEl.classList.remove('d-none');
        document.getElementById('change-password-form').reset();
    } catch (err) {
        resultEl.className = 'mt-3 alert alert-danger';
        resultEl.textContent = err.message;
        resultEl.classList.remove('d-none');
    }
});

function showSettingsAlert(type, msg) {
    const el = document.getElementById('settings-alert');
    el.className = `alert alert-${type} alert-dismissible fade show`;
    el.innerHTML = `${msg}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
    el.classList.remove('d-none');
    setTimeout(() => el.classList.add('d-none'), 5000);
}

// Branding form
document.getElementById('settings-branding-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        await api('PUT', '/settings/system', {
            branding_name: document.getElementById('cfg-branding-name').value || 'NetBird MSP Appliance',
            branding_subtitle: document.getElementById('cfg-branding-subtitle').value || 'Multi-Tenant Management Platform',
            default_language: document.getElementById('cfg-default-language').value || 'en',
        });
        showSettingsAlert('success', t('messages.brandingNameSaved'));
        await loadBranding();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
});

async function uploadLogo() {
    const fileInput = document.getElementById('branding-logo-file');
    if (!fileInput.files.length) {
        showSettingsAlert('danger', t('errors.selectFileFirst'));
        return;
    }
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const resp = await fetch('/api/settings/branding/logo', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${authToken}` },
            body: formData,
        });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || t('errors.uploadFailed'));
        }
        updateLogoPreview(data.branding_logo_path);
        showSettingsAlert('success', t('messages.logoUploaded'));
        fileInput.value = '';
        await loadBranding();
    } catch (err) {
        showSettingsAlert('danger', t('errors.logoUploadFailed', { error: err.message }));
    }
}

async function deleteLogo() {
    try {
        await api('DELETE', '/settings/branding/logo');
        updateLogoPreview(null);
        showSettingsAlert('success', t('messages.logoRemoved'));
        await loadBranding();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failedToRemoveLogo', { error: err.message }));
    }
}

// ---------------------------------------------------------------------------
// DNS Settings
// ---------------------------------------------------------------------------
document.getElementById('settings-dns-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        dns_enabled: document.getElementById('cfg-dns-enabled').checked,
        dns_server: document.getElementById('cfg-dns-server').value,
        dns_zone: document.getElementById('cfg-dns-zone').value,
        dns_username: document.getElementById('cfg-dns-username').value,
        dns_record_ip: document.getElementById('cfg-dns-record-ip').value,
    };
    const pw = document.getElementById('cfg-dns-password').value;
    if (pw) payload.dns_password = pw;
    try {
        await api('PUT', '/settings/system', payload);
        showSettingsAlert('success', t('messages.dnsSettingsSaved'));
        document.getElementById('cfg-dns-password').value = '';
        loadSettings();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
});

async function testDnsConnection() {
    const spinner = document.getElementById('dns-test-spinner');
    const resultEl = document.getElementById('dns-test-result');
    spinner.classList.remove('d-none');
    resultEl.classList.add('d-none');
    try {
        const data = await api('GET', '/settings/test-dns');
        resultEl.className = `mt-3 alert alert-${data.ok ? 'success' : 'danger'}`;
        resultEl.textContent = data.message;
        resultEl.classList.remove('d-none');
    } catch (err) {
        resultEl.className = 'mt-3 alert alert-danger';
        resultEl.textContent = err.message;
        resultEl.classList.remove('d-none');
    } finally {
        spinner.classList.add('d-none');
    }
}

// ---------------------------------------------------------------------------
// LDAP Settings
// ---------------------------------------------------------------------------
document.getElementById('settings-ldap-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        ldap_enabled: document.getElementById('cfg-ldap-enabled').checked,
        ldap_server: document.getElementById('cfg-ldap-server').value,
        ldap_port: parseInt(document.getElementById('cfg-ldap-port').value) || 389,
        ldap_use_ssl: document.getElementById('cfg-ldap-use-ssl').checked,
        ldap_bind_dn: document.getElementById('cfg-ldap-bind-dn').value,
        ldap_base_dn: document.getElementById('cfg-ldap-base-dn').value,
        ldap_user_filter: document.getElementById('cfg-ldap-user-filter').value,
        ldap_group_dn: document.getElementById('cfg-ldap-group-dn').value,
    };
    const pw = document.getElementById('cfg-ldap-bind-password').value;
    if (pw) payload.ldap_bind_password = pw;
    try {
        await api('PUT', '/settings/system', payload);
        showSettingsAlert('success', t('messages.ldapSettingsSaved'));
        document.getElementById('cfg-ldap-bind-password').value = '';
        loadSettings();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
});

async function testLdapConnection() {
    const spinner = document.getElementById('ldap-test-spinner');
    const resultEl = document.getElementById('ldap-test-result');
    spinner.classList.remove('d-none');
    resultEl.classList.add('d-none');
    try {
        const data = await api('GET', '/settings/test-ldap');
        resultEl.className = `mt-3 alert alert-${data.ok ? 'success' : 'danger'}`;
        resultEl.textContent = data.message;
        resultEl.classList.remove('d-none');
    } catch (err) {
        resultEl.className = 'mt-3 alert alert-danger';
        resultEl.textContent = err.message;
        resultEl.classList.remove('d-none');
    } finally {
        spinner.classList.add('d-none');
    }
}

async function loadGitBranches() {
    const branchSelect = document.getElementById('cfg-git-branch');
    const currentVal = branchSelect.value;

    // Disable mapping while loading
    branchSelect.disabled = true;
    branchSelect.innerHTML = `<option value="${currentVal}">${currentVal} (Loading...)</option>`;

    try {
        const branches = await api('GET', '/settings/branches');
        branchSelect.innerHTML = '';

        // Always ensure the currently saved branch is an option
        if (currentVal && !branches.includes(currentVal)) {
            branches.unshift(currentVal);
        }

        if (branches.length === 0) {
            branchSelect.innerHTML = `<option value="main">main</option>`;
        } else {
            branches.forEach(b => {
                const opt = document.createElement('option');
                opt.value = b;
                opt.textContent = b;
                if (b === currentVal) opt.selected = true;
                branchSelect.appendChild(opt);
            });
        }
    } catch (err) {
        showSettingsAlert('warning', `Failed to load branches: ${err.message}`);
        branchSelect.innerHTML = `<option value="${currentVal}">${currentVal}</option>`;
    } finally {
        branchSelect.disabled = false;
    }
}

// ---------------------------------------------------------------------------
// Update / Version Management
// ---------------------------------------------------------------------------
document.getElementById('settings-git-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        git_repo_url: document.getElementById('cfg-git-repo-url').value,
        git_branch: document.getElementById('cfg-git-branch').value || 'main',
    };
    const token = document.getElementById('cfg-git-token').value;
    if (token) payload.git_token = token;
    try {
        await api('PUT', '/settings/system', payload);
        showSettingsAlert('success', t('messages.gitSettingsSaved'));
        document.getElementById('cfg-git-token').value = '';
        loadSettings();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
});

async function loadVersionInfo() {
    const el = document.getElementById('version-info-content');
    if (!el) return;
    el.innerHTML = `<div class="text-muted">${t('common.loading')}</div>`;
    try {
        const data = await api('GET', '/settings/version');
        const current = data.current || {};
        const latest = data.latest;
        const needsUpdate = data.needs_update;

        const currentTag = current.tag && current.tag !== 'unknown' ? current.tag : null;
        const currentCommit = current.commit || 'unknown';

        let html = `<div class="row g-3">
            <div class="col-md-6">
                <div class="border rounded p-3 h-100">
                    <div class="text-muted small mb-1">${t('settings.currentVersion')}</div>
                    <div class="fw-bold fs-5">${esc(currentTag || currentCommit)}</div>
                    ${currentTag ? `<div class="text-muted small font-monospace">${t('settings.commitHash')}: ${esc(currentCommit)}</div>` : ''}
                    <div class="text-muted small">${t('settings.branch')}: <strong>${esc(current.branch || 'unknown')}</strong></div>
                    <div class="text-muted small mt-2"><i class="bi bi-clock me-1"></i>${formatDate(current.date)}</div>
                </div>
            </div>`;

        if (latest) {
            const latestTag = latest.tag && latest.tag !== 'unknown' ? latest.tag : null;
            const latestCommit = latest.commit || 'unknown';
            const badge = needsUpdate
                ? `<span class="badge bg-warning text-dark ms-1">${t('settings.updateAvailable')}</span>`
                : `<span class="badge bg-success ms-1">${t('settings.upToDate')}</span>`;
            html += `<div class="col-md-6">
                <div class="border rounded p-3 h-100 ${needsUpdate ? 'border-warning' : ''}">
                    <div class="text-muted small mb-1">${t('settings.latestVersion')} ${badge}</div>
                    <div class="fw-bold fs-5">${esc(latestTag || latestCommit)}</div>
                    ${latestTag ? `<div class="text-muted small font-monospace">${t('settings.commitHash')}: ${esc(latestCommit)}</div>` : ''}
                    <div class="text-muted small">${t('settings.branch')}: <strong>${esc(latest.branch || 'unknown')}</strong></div>
                    <div class="text-muted small mt-2"><i class="bi bi-clock me-1"></i>${formatDate(latest.date)}</div>
                    ${latest.message ? `<div class="text-muted small mt-1 border-top pt-1 text-truncate" title="${esc(latest.message)}"><i class="bi bi-chat-text me-1"></i>${esc(latest.message)}</div>` : ''}
                </div>
            </div>`;
        } else if (data.error) {
            html += `<div class="col-md-6"><div class="alert alert-warning h-100 mb-0">${esc(data.error)}</div></div>`;
        }
        html += '</div>';

        if (needsUpdate) {
            html += `<div class="mt-3">
                <button class="btn btn-warning" onclick="triggerUpdate()">
                    <span class="spinner-border spinner-border-sm d-none me-1" id="update-spinner"></span>
                    <i class="bi bi-arrow-repeat me-1"></i>${t('settings.triggerUpdate')}
                </button>
                <div class="text-muted small mt-1">${t('settings.updateWarning')}</div>
            </div>`;
        }
        el.innerHTML = html;
    } catch (err) {
        el.innerHTML = `<div class="text-danger">${esc(err.message)}</div>`;
    }
}

async function triggerUpdate() {
    if (!confirm(t('settings.confirmUpdate'))) return;
    const spinner = document.getElementById('update-spinner');
    if (spinner) spinner.classList.remove('d-none');
    try {
        const data = await api('POST', '/settings/update');
        showSettingsAlert('success', data.message || t('messages.updateStarted'));
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
        if (spinner) spinner.classList.add('d-none');
    }
}

// ---------------------------------------------------------------------------
// User Management
// ---------------------------------------------------------------------------
async function loadUsers() {
    try {
        const users = await api('GET', '/users');
        const tbody = document.getElementById('users-table-body');
        if (!users || users.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted py-4">${t('settings.noUsersFound') || t('common.loading')}</td></tr>`;
            return;
        }
        tbody.innerHTML = users.map(u => {
            const langDisplay = u.default_language ? u.default_language.toUpperCase() : `<span class="text-muted">${t('settings.systemDefault')}</span>`;
            const mfaDisplay = u.totp_enabled
                ? `<span class="badge bg-success">${t('mfa.totpActive')}</span>`
                : `<span class="text-muted">&mdash;</span>`;
            return `<tr>
            <td>${u.id}</td>
            <td><strong>${esc(u.username)}</strong></td>
            <td>${esc(u.email || '-')}</td>
            <td><span class="badge bg-info">${esc(u.role || 'admin')}</span></td>
            <td><span class="badge bg-${u.auth_provider === 'azure' ? 'primary' : 'secondary'}">${esc(u.auth_provider || 'local')}</span></td>
            <td>${langDisplay}</td>
            <td>${mfaDisplay}</td>
            <td>${u.is_active ? `<span class="badge bg-success">${t('common.active')}</span>` : `<span class="badge bg-danger">${t('common.disabled')}</span>`}</td>
            <td>
                <div class="btn-group btn-group-sm">
                    ${u.is_active
                    ? `<button class="btn btn-outline-warning" title="${t('common.disable')}" onclick="toggleUserActive(${u.id}, false)"><i class="bi bi-pause-circle"></i></button>`
                    : `<button class="btn btn-outline-success" title="${t('common.enable')}" onclick="toggleUserActive(${u.id}, true)"><i class="bi bi-play-circle"></i></button>`
                }
                    ${u.auth_provider === 'local' ? `<button class="btn btn-outline-info" title="${t('common.resetPassword')}" onclick="resetUserPassword(${u.id}, '${esc(u.username)}')"><i class="bi bi-key"></i></button>` : ''}
                    ${u.totp_enabled ? `<button class="btn btn-outline-secondary" title="${t('mfa.resetMfa')}" onclick="resetUserMfa(${u.id}, '${esc(u.username)}')"><i class="bi bi-shield-x"></i></button>` : ''}
                    <button class="btn btn-outline-danger" title="${t('common.delete')}" onclick="deleteUser(${u.id}, '${esc(u.username)}')"><i class="bi bi-trash"></i></button>
                </div>
            </td>
        </tr>`;
        }).join('');
    } catch (err) {
        document.getElementById('users-table-body').innerHTML = `<tr><td colspan="9" class="text-danger">${err.message}</td></tr>`;
    }
}

function showNewUserModal() {
    document.getElementById('user-form').reset();
    document.getElementById('user-modal-error').classList.add('d-none');
    new bootstrap.Modal(document.getElementById('user-modal')).show();
}

async function saveNewUser() {
    const errorEl = document.getElementById('user-modal-error');
    errorEl.classList.add('d-none');

    const langValue = document.getElementById('new-user-language').value;
    const payload = {
        username: document.getElementById('new-user-username').value,
        password: document.getElementById('new-user-password').value,
        email: document.getElementById('new-user-email').value || null,
        default_language: langValue || null,
    };

    try {
        await api('POST', '/users', payload);
        bootstrap.Modal.getInstance(document.getElementById('user-modal')).hide();
        showSettingsAlert('success', t('messages.userCreated', { username: payload.username }));
        loadUsers();
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('d-none');
    }
}

async function deleteUser(id, username) {
    if (!confirm(t('messages.confirmDeleteUser', { username }))) return;
    try {
        await api('DELETE', `/users/${id}`);
        showSettingsAlert('success', t('messages.userDeleted', { username }));
        loadUsers();
    } catch (err) {
        showSettingsAlert('danger', t('errors.deleteFailed', { error: err.message }));
    }
}

async function toggleUserActive(id, active) {
    try {
        await api('PUT', `/users/${id}`, { is_active: active });
        loadUsers();
    } catch (err) {
        showSettingsAlert('danger', t('errors.updateFailed', { error: err.message }));
    }
}

async function resetUserPassword(id, username) {
    if (!confirm(t('messages.confirmResetPassword', { username }))) return;
    try {
        const data = await api('POST', `/users/${id}/reset-password`);
        alert(t('messages.newPasswordAlert', { username, password: data.new_password }));
        showSettingsAlert('success', t('messages.passwordResetFor', { username }));
    } catch (err) {
        showSettingsAlert('danger', t('errors.passwordResetFailed', { error: err.message }));
    }
}

// ---------------------------------------------------------------------------
// Azure AD Settings
// ---------------------------------------------------------------------------
document.getElementById('settings-azure-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        azure_enabled: document.getElementById('cfg-azure-enabled').checked,
        azure_tenant_id: document.getElementById('cfg-azure-tenant').value || null,
        azure_client_id: document.getElementById('cfg-azure-client-id').value || null,
        azure_allowed_group_id: document.getElementById('cfg-azure-group-id').value || null,
    };
    const secret = document.getElementById('cfg-azure-client-secret').value;
    if (secret) payload.azure_client_secret = secret;

    try {
        await api('PUT', '/settings/system', payload);
        showSettingsAlert('success', t('messages.azureSettingsSaved'));
        document.getElementById('cfg-azure-client-secret').value = '';
        loadSettings();
        await loadAzureLoginConfig();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
});

// ---------------------------------------------------------------------------
// MFA Settings
// ---------------------------------------------------------------------------
async function saveMfaSettings() {
    try {
        await api('PUT', '/settings/system', {
            mfa_enabled: document.getElementById('cfg-mfa-enabled').checked,
        });
        showSettingsAlert('success', t('mfa.mfaSaved'));
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
}

async function loadMfaStatus() {
    try {
        const data = await api('GET', '/auth/mfa/status');
        document.getElementById('cfg-mfa-enabled').checked = data.mfa_enabled_global;

        const statusEl = document.getElementById('mfa-own-status');
        const disableBtn = document.getElementById('mfa-disable-own');

        if (data.totp_enabled_user) {
            statusEl.innerHTML = `<span class="badge bg-success">${t('mfa.totpActive')}</span>`;
            disableBtn.classList.remove('d-none');
        } else {
            statusEl.innerHTML = `<span class="badge bg-warning text-dark">${t('mfa.totpNotSetUp')}</span>`;
            disableBtn.classList.add('d-none');
        }
    } catch (err) {
        console.error('Failed to load MFA status:', err);
    }
}

async function disableOwnTotp() {
    try {
        await api('POST', '/auth/mfa/disable');
        showSettingsAlert('success', t('mfa.mfaDisabled'));
        loadMfaStatus();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
}

async function resetUserMfa(id, username) {
    if (!confirm(t('mfa.confirmResetMfa', { username }))) return;
    try {
        await api('POST', `/users/${id}/reset-mfa`);
        showSettingsAlert('success', t('mfa.mfaResetSuccess', { username }));
        loadUsers();
    } catch (err) {
        showSettingsAlert('danger', t('errors.failed', { error: err.message }));
    }
}

function togglePasswordVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const isHidden = input.type === 'password';
    input.type = isHidden ? 'text' : 'password';
    const btn = input.parentElement.querySelector('[data-toggle-pw]');
    if (btn) {
        const icon = btn.querySelector('i');
        if (icon) icon.className = isHidden ? 'bi bi-eye-slash' : 'bi bi-eye';
    }
}

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------
async function loadMonitoring() {
    await Promise.all([loadResources(), loadAllCustomerStatuses()]);
}

async function loadResources() {
    try {
        const data = await api('GET', '/monitoring/resources');
        document.getElementById('monitoring-resources').innerHTML = `
            <div class="row g-3">
                <div class="col-md-3">
                    <div class="text-muted small">${t('monitoring.hostname')}</div>
                    <div class="fw-bold">${esc(data.hostname)}</div>
                    <div class="text-muted small">${esc(data.os)}</div>
                </div>
                <div class="col-md-3">
                    <div class="text-muted small">${t('monitoring.cpu', { count: data.cpu.count })}</div>
                    <div class="progress mt-1" style="height: 20px;">
                        <div class="progress-bar ${data.cpu.percent > 80 ? 'bg-danger' : data.cpu.percent > 50 ? 'bg-warning' : 'bg-success'}"
                             style="width: ${data.cpu.percent}%">${data.cpu.percent}%</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="text-muted small">${t('monitoring.memory', { used: data.memory.used_gb, total: data.memory.total_gb })}</div>
                    <div class="progress mt-1" style="height: 20px;">
                        <div class="progress-bar ${data.memory.percent > 80 ? 'bg-danger' : data.memory.percent > 50 ? 'bg-warning' : 'bg-success'}"
                             style="width: ${data.memory.percent}%">${data.memory.percent}%</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="text-muted small">${t('monitoring.disk', { used: data.disk.used_gb, total: data.disk.total_gb })}</div>
                    <div class="progress mt-1" style="height: 20px;">
                        <div class="progress-bar ${data.disk.percent > 80 ? 'bg-danger' : data.disk.percent > 50 ? 'bg-warning' : 'bg-success'}"
                             style="width: ${data.disk.percent}%">${data.disk.percent}%</div>
                    </div>
                </div>
            </div>
        `;
    } catch (err) {
        document.getElementById('monitoring-resources').innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

async function loadAllCustomerStatuses() {
    try {
        const data = await api('GET', '/monitoring/customers');
        const tbody = document.getElementById('monitoring-customers-body');
        if (!data || data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">${t('monitoring.noCustomers')}</td></tr>`;
            return;
        }
        tbody.innerHTML = data.map(c => {
            const containerInfo = c.containers.map(ct => `${ct.name}: ${ct.status}`).join(', ') || '-';
            const dashPort = c.dashboard_port;
            const dashLink = dashPort
                ? `<a href="${esc(c.setup_url || 'http://localhost:' + dashPort)}" target="_blank">:${dashPort}</a>`
                : '-';
            return `<tr>
                <td>${c.id}</td>
                <td>${esc(c.name)}</td>
                <td><code>${esc(c.subdomain)}</code></td>
                <td>${statusBadge(c.status)}</td>
                <td>${c.deployment_status ? statusBadge(c.deployment_status) : '-'}</td>
                <td>${dashLink}</td>
                <td>${c.relay_udp_port || '-'}</td>
                <td class="small">${esc(containerInfo)}</td>
            </tr>`;
        }).join('');
    } catch (err) {
        document.getElementById('monitoring-customers-body').innerHTML = `<tr><td colspan="8" class="text-danger">${err.message}</td></tr>`;
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function statusBadge(status) {
    const map = {
        active: 'success', running: 'success',
        inactive: 'secondary', stopped: 'secondary',
        deploying: 'info', pending: 'info',
        error: 'danger', failed: 'danger',
    };
    const color = map[status] || 'secondary';
    return `<span class="badge bg-${color}">${status}</span>`;
}

function formatDate(isoStr) {
    if (!isoStr) return '-';
    const locale = getCurrentLanguage() === 'de' ? 'de-DE' : 'en-US';
    const d = new Date(isoStr);
    return d.toLocaleDateString(locale) + ' ' + d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
}

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function debounce(fn, delay) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

function showToast(message) {
    // Simple inline notification
    const el = document.createElement('div');
    el.className = 'toast-notification';
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
    // Check for Azure AD callback first
    const params = new URLSearchParams(window.location.search);
    if (params.has('code')) {
        await initI18n();
        await loadBranding();
        const handled = await handleAzureCallback();
        if (handled) return;
    }
    initApp();
});
