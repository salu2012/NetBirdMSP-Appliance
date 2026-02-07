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
        throw new Error('Network error — server not reachable.');
    }
    if (resp.status === 401) {
        logout();
        throw new Error('Session expired.');
    }
    let data;
    try {
        data = await resp.json();
    } catch (jsonErr) {
        console.error(`API JSON parse error: ${method} ${path} (status ${resp.status})`, jsonErr);
        throw new Error(`Server error (HTTP ${resp.status}).`);
    }
    if (!resp.ok) {
        const msg = data.detail || data.message || 'Request failed.';
        console.error(`API error: ${method} ${path} (status ${resp.status})`, msg);
        throw new Error(msg);
    }
    return data;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
function initApp() {
    if (authToken) {
        api('GET', '/auth/me')
            .then(user => {
                currentUser = user;
                document.getElementById('nav-username').textContent = user.username;
                showAppPage();
                loadDashboard();
            })
            .catch(() => {
                authToken = null;
                localStorage.removeItem('authToken');
                showLoginPage();
            });
    } else {
        showLoginPage();
    }
}

function showLoginPage() {
    document.getElementById('login-page').classList.remove('d-none');
    document.getElementById('app-page').classList.add('d-none');
}

function showAppPage() {
    document.getElementById('login-page').classList.add('d-none');
    document.getElementById('app-page').classList.remove('d-none');
}

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
        authToken = data.access_token;
        localStorage.setItem('authToken', authToken);
        currentUser = data.user;
        document.getElementById('nav-username').textContent = currentUser.username;
        showAppPage();
        loadDashboard();
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('d-none');
    } finally {
        spinner.classList.add('d-none');
    }
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
        }).catch(() => {});
    }
    authToken = null;
    currentUser = null;
    localStorage.removeItem('authToken');
    showLoginPage();
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
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">No customers found. Click "New Customer" to create one.</td></tr>';
        document.getElementById('pagination-info').textContent = 'Showing 0 of 0';
        document.getElementById('pagination-controls').innerHTML = '';
        return;
    }

    tbody.innerHTML = data.items.map(c => `
        <tr>
            <td>${c.id}</td>
            <td><a href="#" onclick="viewCustomer(${c.id})" class="text-decoration-none fw-semibold">${esc(c.name)}</a></td>
            <td>${esc(c.company || '-')}</td>
            <td><code>${esc(c.subdomain)}</code></td>
            <td>${statusBadge(c.status)}</td>
            <td>${c.max_devices}</td>
            <td>${formatDate(c.created_at)}</td>
            <td>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary" title="View" onclick="viewCustomer(${c.id})"><i class="bi bi-eye"></i></button>
                    ${c.deployment && c.deployment.deployment_status === 'running'
                        ? `<button class="btn btn-outline-warning" title="Stop" onclick="customerAction(${c.id},'stop')"><i class="bi bi-stop-circle"></i></button>`
                        : `<button class="btn btn-outline-success" title="Start" onclick="customerAction(${c.id},'start')"><i class="bi bi-play-circle"></i></button>`
                    }
                    <button class="btn btn-outline-info" title="Restart" onclick="customerAction(${c.id},'restart')"><i class="bi bi-arrow-repeat"></i></button>
                    <button class="btn btn-outline-danger" title="Delete" onclick="showDeleteModal(${c.id},'${esc(c.name)}')"><i class="bi bi-trash"></i></button>
                </div>
            </td>
        </tr>
    `).join('');

    // Pagination
    const start = (data.page - 1) * data.per_page + 1;
    const end = Math.min(data.page * data.per_page, data.total);
    document.getElementById('pagination-info').textContent = `Showing ${start}-${end} of ${data.total}`;

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
    document.getElementById('customer-modal-title').textContent = 'New Customer';
    document.getElementById('customer-edit-id').value = '';
    document.getElementById('customer-form').reset();
    document.getElementById('cust-max-devices').value = '20';
    document.getElementById('customer-modal-error').classList.add('d-none');
    document.getElementById('customer-save-btn').innerHTML = '<span class="spinner-border spinner-border-sm d-none me-1" id="customer-save-spinner"></span> Save &amp; Deploy';

    // Update subdomain suffix
    api('GET', '/settings/system').then(cfg => {
        document.getElementById('cust-subdomain-suffix').textContent = `.${cfg.base_domain || 'domain.com'}`;
    }).catch(() => {});

    const modalEl = document.getElementById('customer-modal');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    // Enable subdomain field for new customers
    document.getElementById('cust-subdomain').disabled = false;
    modal.show();
}

function editCurrentCustomer() {
    if (!currentCustomerData) return;
    const c = currentCustomerData;
    document.getElementById('customer-modal-title').textContent = 'Edit Customer';
    document.getElementById('customer-edit-id').value = c.id;
    document.getElementById('cust-name').value = c.name;
    document.getElementById('cust-company').value = c.company || '';
    document.getElementById('cust-subdomain').value = c.subdomain;
    document.getElementById('cust-subdomain').disabled = true; // Can't change subdomain
    document.getElementById('cust-email').value = c.email;
    document.getElementById('cust-max-devices').value = c.max_devices;
    document.getElementById('cust-notes').value = c.notes || '';
    document.getElementById('customer-modal-error').classList.add('d-none');
    document.getElementById('customer-save-btn').innerHTML = '<span class="spinner-border spinner-border-sm d-none me-1" id="customer-save-spinner"></span> Save Changes';

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
        errorEl.textContent = err.message || 'An unknown error occurred.';
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
        alert('Delete failed: ' + err.message);
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
        alert(`${action} failed: ${err.message}`);
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
                <div class="col-md-6"><strong>Name:</strong> ${esc(data.name)}</div>
                <div class="col-md-6"><strong>Company:</strong> ${esc(data.company || '-')}</div>
                <div class="col-md-6"><strong>Subdomain:</strong> <code>${esc(data.subdomain)}</code></div>
                <div class="col-md-6"><strong>Email:</strong> ${esc(data.email)}</div>
                <div class="col-md-6"><strong>Max Devices:</strong> ${data.max_devices}</div>
                <div class="col-md-6"><strong>Status:</strong> ${statusBadge(data.status)}</div>
                <div class="col-md-6"><strong>Created:</strong> ${formatDate(data.created_at)}</div>
                <div class="col-md-6"><strong>Updated:</strong> ${formatDate(data.updated_at)}</div>
                ${data.notes ? `<div class="col-12"><strong>Notes:</strong> ${esc(data.notes)}</div>` : ''}
            </div>
        `;

        // Deployment tab
        if (data.deployment) {
            const d = data.deployment;
            document.getElementById('detail-deployment-content').innerHTML = `
                <div class="row g-3">
                    <div class="col-md-6"><strong>Status:</strong> ${statusBadge(d.deployment_status)}</div>
                    <div class="col-md-6"><strong>Relay UDP Port:</strong> ${d.relay_udp_port}</div>
                    <div class="col-md-6"><strong>Container Prefix:</strong> <code>${esc(d.container_prefix)}</code></div>
                    <div class="col-md-6"><strong>Deployed:</strong> ${formatDate(d.deployed_at)}</div>
                    <div class="col-12">
                        <strong>Setup URL:</strong>
                        <div class="input-group mt-1">
                            <input type="text" class="form-control" value="${esc(d.setup_url || '')}" readonly id="setup-url-input">
                            <button class="btn btn-outline-secondary" onclick="copySetupUrl()"><i class="bi bi-clipboard"></i> Copy</button>
                        </div>
                    </div>
                </div>
                <div class="mt-3">
                    <button class="btn btn-success btn-sm me-1" onclick="customerAction(${id},'start')"><i class="bi bi-play-circle me-1"></i>Start</button>
                    <button class="btn btn-warning btn-sm me-1" onclick="customerAction(${id},'stop')"><i class="bi bi-stop-circle me-1"></i>Stop</button>
                    <button class="btn btn-info btn-sm me-1" onclick="customerAction(${id},'restart')"><i class="bi bi-arrow-repeat me-1"></i>Restart</button>
                    <button class="btn btn-outline-primary btn-sm" onclick="customerAction(${id},'deploy')"><i class="bi bi-rocket me-1"></i>Re-Deploy</button>
                </div>
            `;
        } else {
            document.getElementById('detail-deployment-content').innerHTML = `
                <p class="text-muted">No deployment found.</p>
                <button class="btn btn-primary" onclick="customerAction(${id},'deploy')"><i class="bi bi-rocket me-1"></i>Deploy Now</button>
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
            content.innerHTML = '<p class="text-muted">No container logs available.</p>';
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
        let html = `<div class="mb-3"><strong>Overall:</strong> ${data.healthy ? '<span class="text-success">Healthy</span>' : '<span class="text-danger">Unhealthy</span>'}</div>`;
        if (data.containers && data.containers.length > 0) {
            html += '<table class="table table-sm"><thead><tr><th>Container</th><th>Status</th><th>Health</th><th>Image</th></tr></thead><tbody>';
            data.containers.forEach(c => {
                const statusClass = c.status === 'running' ? 'text-success' : 'text-danger';
                html += `<tr><td>${esc(c.name)}</td><td class="${statusClass}">${c.status}</td><td>${c.health}</td><td><code>${esc(c.image)}</code></td></tr>`;
            });
            html += '</tbody></table>';
        }
        html += `<div class="text-muted small">Last check: ${formatDate(data.last_check)}</div>`;
        content.innerHTML = html;
    } catch (err) {
        document.getElementById('detail-health-content').innerHTML = `<div class="alert alert-danger">${err.message}</div>`;
    }
}

function copySetupUrl() {
    const input = document.getElementById('setup-url-input');
    navigator.clipboard.writeText(input.value).then(() => {
        showToast('Setup URL copied to clipboard.');
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
        document.getElementById('cfg-npm-api-url').value = cfg.npm_api_url || '';
        document.getElementById('npm-credentials-status').textContent = cfg.npm_credentials_set ? 'Credentials are set (leave empty to keep current)' : 'No NPM credentials configured';
        document.getElementById('cfg-mgmt-image').value = cfg.netbird_management_image || '';
        document.getElementById('cfg-signal-image').value = cfg.netbird_signal_image || '';
        document.getElementById('cfg-relay-image').value = cfg.netbird_relay_image || '';
        document.getElementById('cfg-dashboard-image').value = cfg.netbird_dashboard_image || '';
    } catch (err) {
        showSettingsAlert('danger', 'Failed to load settings: ' + err.message);
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
        });
        showSettingsAlert('success', 'System settings saved.');
    } catch (err) {
        showSettingsAlert('danger', 'Failed: ' + err.message);
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
    try {
        await api('PUT', '/settings/system', payload);
        showSettingsAlert('success', 'NPM settings saved.');
        document.getElementById('cfg-npm-api-email').value = '';
        document.getElementById('cfg-npm-api-password').value = '';
        loadSettings();
    } catch (err) {
        showSettingsAlert('danger', 'Failed: ' + err.message);
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
        showSettingsAlert('success', 'Image settings saved.');
    } catch (err) {
        showSettingsAlert('danger', 'Failed: ' + err.message);
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

// Change password form
document.getElementById('change-password-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const resultEl = document.getElementById('password-result');
    const newPw = document.getElementById('pw-new').value;
    const confirmPw = document.getElementById('pw-confirm').value;

    if (newPw !== confirmPw) {
        resultEl.className = 'mt-3 alert alert-danger';
        resultEl.textContent = 'Passwords do not match.';
        resultEl.classList.remove('d-none');
        return;
    }

    try {
        await api('POST', '/auth/change-password', {
            current_password: document.getElementById('pw-current').value,
            new_password: newPw,
        });
        resultEl.className = 'mt-3 alert alert-success';
        resultEl.textContent = 'Password changed successfully.';
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

function togglePasswordVisibility(inputId) {
    const input = document.getElementById(inputId);
    input.type = input.type === 'password' ? 'text' : 'password';
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
                    <div class="text-muted small">Hostname</div>
                    <div class="fw-bold">${esc(data.hostname)}</div>
                    <div class="text-muted small">${esc(data.os)}</div>
                </div>
                <div class="col-md-3">
                    <div class="text-muted small">CPU (${data.cpu.count} cores)</div>
                    <div class="progress mt-1" style="height: 20px;">
                        <div class="progress-bar ${data.cpu.percent > 80 ? 'bg-danger' : data.cpu.percent > 50 ? 'bg-warning' : 'bg-success'}"
                             style="width: ${data.cpu.percent}%">${data.cpu.percent}%</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="text-muted small">Memory (${data.memory.used_gb}/${data.memory.total_gb} GB)</div>
                    <div class="progress mt-1" style="height: 20px;">
                        <div class="progress-bar ${data.memory.percent > 80 ? 'bg-danger' : data.memory.percent > 50 ? 'bg-warning' : 'bg-success'}"
                             style="width: ${data.memory.percent}%">${data.memory.percent}%</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="text-muted small">Disk (${data.disk.used_gb}/${data.disk.total_gb} GB)</div>
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
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">No customers.</td></tr>';
            return;
        }
        tbody.innerHTML = data.map(c => {
            const containerInfo = c.containers.map(ct => `${ct.name}: ${ct.status}`).join(', ') || '-';
            return `<tr>
                <td>${c.id}</td>
                <td>${esc(c.name)}</td>
                <td><code>${esc(c.subdomain)}</code></td>
                <td>${statusBadge(c.status)}</td>
                <td>${c.deployment_status ? statusBadge(c.deployment_status) : '-'}</td>
                <td>${c.relay_udp_port || '-'}</td>
                <td class="small">${esc(containerInfo)}</td>
            </tr>`;
        }).join('');
    } catch (err) {
        document.getElementById('monitoring-customers-body').innerHTML = `<tr><td colspan="7" class="text-danger">${err.message}</td></tr>`;
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
    const d = new Date(isoStr);
    return d.toLocaleDateString('de-DE') + ' ' + d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
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
document.addEventListener('DOMContentLoaded', initApp);
