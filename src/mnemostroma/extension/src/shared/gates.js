/** @file gates.js — Gate verification logic for DOM-independent rollout */
import { calculateRates } from './metrics.js';

/**
 * Пороги для прохождения гейтов (SPEC_capture_rollout_gates_v1.0.md)
 */
export const GATE_THRESHOLDS = {
  GATE_A: {
    transport_success_rate: 95,
    parse_error_rate: 2,
    sample_size: 500
  },
  GATE_B: {
    transport_success_rate: 99,
    duplicate_drop_rate: 1,
    finalization_timeout_rate: 0.5,
    sample_size: 2000
  }
};

/**
 * Проверяет, проходит ли провайдер условия указанного гейта.
 * @param {Object} metrics - Сырые метрики провайдера
 * @param {string} gateType - 'GATE_A' или 'GATE_B'
 * @returns {Object} { pass: boolean, reason?: string }
 */
export function checkGate(metrics, gateType) {
  const rates = calculateRates(metrics);
  const thresholds = GATE_THRESHOLDS[gateType];
  
  if (!thresholds) {
    return { pass: false, reason: `Unknown gate type: ${gateType}` };
  }
  
  // 1. Проверка размера выборки (sample_size)
  if (rates.sample_size < thresholds.sample_size) {
    return { 
      pass: false, 
      reason: `Insufficient sample size: ${rates.sample_size}/${thresholds.sample_size}` 
    };
  }
  
  // 2. Проверка Gate A
  if (gateType === 'GATE_A') {
    if (rates.transport_success_rate < thresholds.transport_success_rate) {
      return { pass: false, reason: `Transport success rate too low: ${rates.transport_success_rate.toFixed(1)}%` };
    }
    if (rates.parse_error_rate > thresholds.parse_error_rate) {
      return { pass: false, reason: `Parse error rate too high: ${rates.parse_error_rate.toFixed(1)}%` };
    }
  }
  
  // 3. Проверка Gate B
  if (gateType === 'GATE_B') {
    if (rates.transport_success_rate < thresholds.transport_success_rate) {
      return { pass: false, reason: `Transport success rate too low: ${rates.transport_success_rate.toFixed(1)}%` };
    }
    if (rates.duplicate_drop_rate > thresholds.duplicate_drop_rate) {
      return { pass: false, reason: `Duplicate drop rate too high: ${rates.duplicate_drop_rate.toFixed(1)}%` };
    }
    if (rates.finalization_timeout_rate > thresholds.finalization_timeout_rate) {
      return { pass: false, reason: `Finalization timeout rate too high: ${rates.finalization_timeout_rate.toFixed(1)}%` };
    }
  }
  
  return { pass: true };
}
