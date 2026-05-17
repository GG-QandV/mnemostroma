/** @file artifacts.js — Extract structured artifacts from LLM response DOM */

/**
 * Извлекает артефакты из DOM-элемента ответа LLM.
 * Типы: code, table, formula, diagram, file.
 * Размышления (thinking/details) явно пропускаются.
 * @param {Element} responseElement
 * @returns {Array<{type: string, language?: string, content: string}>}
 */
export function extractArtifacts(responseElement) {
  if (!responseElement) return [];

  const artifacts = [];

  // Работаем на клоне чтобы безопасно удалять thinking-блоки
  const workingEl = responseElement.cloneNode(true);

  // Пропустить thinking/reasoning блоки
  workingEl.querySelectorAll('details, [class*="thinking"], [class*="reasoning"]')
    .forEach(el => el.remove());

  // Код — стандартный паттерн: <pre><code class="language-*">
  // pre.querySelector('code') проверяет вложенность — берём текст из <code>
  workingEl.querySelectorAll('pre').forEach(pre => {
    const codeEl = pre.querySelector('code') ?? pre;
    const languageMatch = codeEl.className.match(/language-(\w+)/);
    const language = languageMatch ? languageMatch[1] : 'text';
    const content  = codeEl.textContent.trim();
    if (content) artifacts.push({ type: 'code', language, content });
  });

  // Таблицы
  workingEl.querySelectorAll('table').forEach(table => {
    artifacts.push({ type: 'table', content: table.outerHTML });
  });

  // Формулы (MathJax / KaTeX)
  workingEl.querySelectorAll('mjx-container, .katex').forEach(el => {
    const latex =
      el.querySelector('[data-latex]')?.dataset.latex ??
      el.getAttribute('data-mathml') ??
      el.textContent.trim();
    if (latex) artifacts.push({ type: 'formula', content: latex });
  });

  // Mermaid диаграммы
  workingEl.querySelectorAll('pre.mermaid, pre[class*="mermaid"]').forEach(pre => {
    const content = pre.textContent.trim();
    if (content) artifacts.push({ type: 'diagram', content });
  });

  // Файлы (ссылки на скачивание)
  workingEl.querySelectorAll('a[download], a[href$=".pdf"], a[href$=".csv"]').forEach(a => {
    if (a.href) artifacts.push({ type: 'file', content: a.href });
  });

  return artifacts;
}
