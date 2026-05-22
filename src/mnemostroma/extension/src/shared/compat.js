/** @file compat.js — Cross-browser API polyfill for Chrome and Firefox */

/**
 * Полифилл для кросс-браузерного API.
 * Единственный файл в проекте где упоминается browser или chrome.
 * Везде остальном используется только импортированный api.
 */
const api = typeof browser !== 'undefined' ? browser : chrome;
export default api;
