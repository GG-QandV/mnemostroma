const GATE_THRESHOLDS = {
  GATE_A: { transport_success_rate: 95, parse_error_rate: 2, sample_size: 500 },
  GATE_B: { transport_success_rate: 99, duplicate_drop_rate: 1, finalization_timeout_rate: 0.5, sample_size: 2000 },
};

export function buildGateSnapshot(providerId, metrics) {
  const total = metrics?.total_finalized || 0;
  const rates = total === 0 ? {
    transport_success_rate: 0,
    dom_fallback_rate: 0,
    parse_error_rate: 0,
    duplicate_drop_rate: 0,
    finalization_timeout_rate: 0,
    sample_size: 0,
  } : {
    transport_success_rate: (metrics.transport_success / total) * 100,
    dom_fallback_rate: (metrics.dom_fallback / total) * 100,
    parse_error_rate: (metrics.parse_error / total) * 100,
    duplicate_drop_rate: (metrics.duplicate_drop / total) * 100,
    finalization_timeout_rate: (metrics.finalization_timeout / total) * 100,
    sample_size: total,
  };

  const gateA = check(rates, 'GATE_A');
  const gateB = check(rates, 'GATE_B');
  return {
    provider: providerId,
    sample_size: rates.sample_size,
    rates,
    gate_a: gateA,
    gate_b: gateB,
    ts: new Date().toISOString(),
  };
}

function check(rates, gate) {
  const t = GATE_THRESHOLDS[gate];
  if (!t) return { pass: false, reason: `Unknown gate type: ${gate}` };
  if (rates.sample_size < t.sample_size) {
    return { pass: false, reason: `Insufficient sample size: ${rates.sample_size}/${t.sample_size}` };
  }

  if (gate === 'GATE_A') {
    if (rates.transport_success_rate < t.transport_success_rate) return { pass: false, reason: 'Transport success rate too low' };
    if (rates.parse_error_rate > t.parse_error_rate) return { pass: false, reason: 'Parse error rate too high' };
  }

  if (gate === 'GATE_B') {
    if (rates.transport_success_rate < t.transport_success_rate) return { pass: false, reason: 'Transport success rate too low' };
    if (rates.duplicate_drop_rate > t.duplicate_drop_rate) return { pass: false, reason: 'Duplicate drop rate too high' };
    if (rates.finalization_timeout_rate > t.finalization_timeout_rate) return { pass: false, reason: 'Finalization timeout rate too high' };
  }
  return { pass: true };
}

