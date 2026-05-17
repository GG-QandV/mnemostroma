// tests/unit/artifacts.test.js — расширенный
import { describe, it, expect } from 'vitest';
import { extractArtifacts } from '../../src/shared/artifacts.js';

function el(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div;
}

describe('extractArtifacts — edge inputs', () => {
  it('returns [] for null', () => {
    expect(extractArtifacts(null)).toEqual([]);
  });
  it('returns [] for empty element', () => {
    expect(extractArtifacts(document.createElement('div'))).toEqual([]);
  });
  it('returns [] for element with only text', () => {
    expect(extractArtifacts(el('<p>hello world</p>'))).toEqual([]);
  });
});

describe('extractArtifacts — code', () => {
  it('extracts code from pre > code with language class', () => {
    const artifacts = extractArtifacts(el('<pre><code class="language-python">print("hi")</code></pre>'));
    expect(artifacts[0]).toMatchObject({ type: 'code', language: 'python', content: 'print("hi")' });
  });
  it('defaults language to "text" when no language class', () => {
    const artifacts = extractArtifacts(el('<pre><code>raw code</code></pre>'));
    expect(artifacts[0]).toMatchObject({ type: 'code', language: 'text' });
  });
  it('uses pre text when no inner code element', () => {
    const artifacts = extractArtifacts(el('<pre>plain pre content</pre>'));
    expect(artifacts[0]).toMatchObject({ type: 'code', content: 'plain pre content' });
  });
  it('skips empty pre blocks', () => {
    const artifacts = extractArtifacts(el('<pre><code>   </code></pre>'));
    expect(artifacts).toHaveLength(0);
  });
  it('extracts multiple code blocks', () => {
    const artifacts = extractArtifacts(el(`
      <pre><code class="language-js">const x = 1;</code></pre>
      <pre><code class="language-py">x = 1</code></pre>
    `));
    expect(artifacts).toHaveLength(2);
    expect(artifacts.map(a => a.language)).toEqual(['js', 'py']);
  });
});

describe('extractArtifacts — table', () => {
  it('extracts table as outerHTML', () => {
    const artifacts = extractArtifacts(el('<table><tr><td>cell</td></tr></table>'));
    expect(artifacts[0].type).toBe('table');
    expect(artifacts[0].content).toContain('<table>');
  });
  it('extracts multiple tables', () => {
    const artifacts = extractArtifacts(el('<table></table><table></table>'));
    expect(artifacts.filter(a => a.type === 'table')).toHaveLength(2);
  });
});

describe('extractArtifacts — thinking blocks skip', () => {
  it('skips <details> blocks', () => {
    const artifacts = extractArtifacts(el('<details><pre><code>secret</code></pre></details>'));
    expect(artifacts).toHaveLength(0);
  });
  it('skips [class*="thinking"] blocks', () => {
    const artifacts = extractArtifacts(el('<div class="thinking-block"><pre><code>hidden</code></pre></div>'));
    expect(artifacts).toHaveLength(0);
  });
  it('skips [class*="reasoning"] blocks', () => {
    const artifacts = extractArtifacts(el('<div class="reasoning"><pre><code>hidden</code></pre></div>'));
    expect(artifacts).toHaveLength(0);
  });
  it('preserves code outside thinking blocks', () => {
    const artifacts = extractArtifacts(el(`
      <details><pre><code>hidden</code></pre></details>
      <pre><code class="language-js">visible</code></pre>
    `));
    expect(artifacts).toHaveLength(1);
    expect(artifacts[0].content).toBe('visible');
  });
});

describe('extractArtifacts — mixed content', () => {
  it('extracts code and table from same response', () => {
    const artifacts = extractArtifacts(el(`
      <pre><code class="language-js">const x = 1;</code></pre>
      <table><tr><td>a</td></tr></table>
    `));
    const types = artifacts.map(a => a.type);
    expect(types).toContain('code');
    expect(types).toContain('table');
  });
  it('does not mutate original element', () => {
    const original = el('<details><summary>thinking</summary></details><pre><code>real</code></pre>');
    const detailsBefore = original.querySelectorAll('details').length;
    extractArtifacts(original);
    expect(original.querySelectorAll('details').length).toBe(detailsBefore);
  });
});
