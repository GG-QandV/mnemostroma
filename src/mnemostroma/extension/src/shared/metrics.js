/** @file metrics.js — Provider-specific capture metrics */
import api from './compat.js';

/**
 * Метрики захвата данных по провайдерам.
 */
export const METRIC_KEYS = {
  TRANSPORT_SUCCESS:   'transport_success',
  DOM_FALLBACK:        'dom_fallback',
  PARSE_ERROR:         'parse_error',
  DUPLICATE_DROP:      'duplicate_drop',
  TIMEOUT:             'finalization_timeout',
  TOTAL:               'total_finalized'
};

/**
 * Получить метрики для конкретного провайдера.
 * @param {string} providerId
 * @returns {Promise<Object>}
 */
export async function getProviderMetrics(providerId) {
  const key = `metrics_${providerId}`;
  const data = await api.storage.local.get(key);
  return data[key] || createEmptyMetrics();
}

/**
 * Создать пустую структуру метрик.
 * @returns {Object}
 */
export function createEmptyMetrics() {
  const m = {};
  Object.values(METRIC_KEYS).forEach(k => m[k] = 0);
  return m;
}

/**
 * Инкрементировать конкретную метрику провайдера.
 * @param {string} providerId
 * @param {string} metricKey
 */
export async function incrementMetric(providerId, metricKey) {
  const key = `metrics_${providerId}`;
  const metrics = await getProviderMetrics(providerId);
  if (Object.values(METRIC_KEYS).includes(metricKey)) {
    metrics[metricKey]++;
    // Если это одна из финальных метрик, инкрементируем и общий счетчик
    if (metricKey === METRIC_KEYS.TRANSPORT_SUCCESS || metricKey === METRIC_KEYS.DOM_FALLBACK) {
      metrics[METRIC_KEYS.TOTAL]++;
    }
    await api.storage.local.set({ [key]: metrics });
  }
}

/**
 * Рассчитать процентные показатели на основе сырых счетчиков.
 * @param {Object} metrics
 * @returns {Object}
 */
export function calculateRates(metrics) {
  const total = metrics[METRIC_KEYS.TOTAL] || 0;
  if (total === 0) return {
    transport_success_rate: 0,
    dom_fallback_rate: 0,
    parse_error_rate: 0,
    duplicate_drop_rate: 0,
    finalization_timeout_rate: 0,
    sample_size: 0
  };

  return {
    transport_success_rate:    (metrics[METRIC_KEYS.TRANSPORT_SUCCESS] / total) * 100,
    dom_fallback_rate:         (metrics[METRIC_KEYS.DOM_FALLBACK] / total) * 100,
    parse_error_rate:          (metrics[METRIC_KEYS.PARSE_ERROR] / total) * 100,
    duplicate_drop_rate:       (metrics[METRIC_KEYS.DUPLICATE_DROP] / total) * 100,
    finalization_timeout_rate: (metrics[METRIC_KEYS.TIMEOUT] / total) * 100,
    sample_size: total
  };
}
