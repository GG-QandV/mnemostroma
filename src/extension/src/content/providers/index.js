import claude from './claude.js';
import chatgpt from './chatgpt.js';
import perplexity from './perplexity.js';
import grok from './grok.js';

const PARSERS = {
  claude,
  chatgpt,
  perplexity,
  grok,
};

export function getProviderParser(shortName) {
  return PARSERS[shortName] ?? null;
}

