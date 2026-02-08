/**
 * i18n - Internationalization for NetBird MSP Appliance
 * Supports: English (en), German (de)
 */

let currentLanguage = null;
let systemDefaultLanguage = 'en';
const translations = {};
const SUPPORTED_LANGS = ['en', 'de'];

function setSystemDefault(lang) {
    if (SUPPORTED_LANGS.includes(lang)) {
        systemDefaultLanguage = lang;
    }
}

function detectLanguage() {
    const stored = localStorage.getItem('language');
    if (stored && SUPPORTED_LANGS.includes(stored)) return stored;
    // Fall back to system default (from server settings)
    if (systemDefaultLanguage && SUPPORTED_LANGS.includes(systemDefaultLanguage)) return systemDefaultLanguage;
    const browser = (navigator.language || '').toLowerCase();
    if (browser.startsWith('de')) return 'de';
    return 'en';
}

async function loadLanguage(lang) {
    if (translations[lang]) return;
    try {
        const resp = await fetch(`/static/lang/${lang}.json`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        translations[lang] = await resp.json();
    } catch (err) {
        console.error(`i18n: failed to load ${lang}`, err);
        if (lang !== 'en') await loadLanguage('en');
    }
}

function t(key, params) {
    const lang = currentLanguage || 'en';
    const dict = translations[lang] || translations['en'] || {};
    let value = key.split('.').reduce((o, k) => (o && o[k] !== undefined) ? o[k] : null, dict);
    if (value === null && lang !== 'en') {
        const en = translations['en'] || {};
        value = key.split('.').reduce((o, k) => (o && o[k] !== undefined) ? o[k] : null, en);
    }
    if (value === null) return key;
    if (params && typeof value === 'string') {
        value = value.replace(/\{(\w+)\}/g, (m, p) => params[p] !== undefined ? params[p] : m);
    }
    return value;
}

function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = t(el.getAttribute('data-i18n'));
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = t(el.getAttribute('data-i18n-title'));
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
        el.innerHTML = t(el.getAttribute('data-i18n-html'));
    });
}

function updateLanguageSwitcher() {
    const btn = document.getElementById('language-switcher-btn');
    if (btn) btn.textContent = (currentLanguage || 'en').toUpperCase();
    document.querySelectorAll('[data-lang]').forEach(el => {
        el.classList.toggle('active', el.getAttribute('data-lang') === currentLanguage);
    });
}

async function setLanguage(lang) {
    if (!SUPPORTED_LANGS.includes(lang)) lang = 'en';
    if (!translations[lang]) await loadLanguage(lang);
    currentLanguage = lang;
    localStorage.setItem('language', lang);
    document.documentElement.lang = lang;
    updateLanguageSwitcher();
    applyTranslations();
}

function getCurrentLanguage() {
    return currentLanguage || 'en';
}

async function initI18n() {
    const lang = detectLanguage();
    await loadLanguage('en');
    if (lang !== 'en') await loadLanguage(lang);
    currentLanguage = lang;
    document.documentElement.lang = lang;
    updateLanguageSwitcher();
    applyTranslations();
    document.body.classList.remove('i18n-loading');
}
