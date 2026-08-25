(() => {
  const library = document.querySelector('[data-paper-library]');
  const main = document.querySelector('main');
  if (!library || !main) return;

  const search = library.querySelector('input[data-paper-search]');
  const filter = library.querySelector('[data-paper-field]');
  const reset = library.querySelector('[data-paper-reset]');
  const count = library.querySelector('[data-paper-count]');
  const empty = library.querySelector('[data-paper-empty]');
  const results = main.querySelector('[data-paper-results]');
  const resultList = results?.querySelector('[data-paper-results-list]');
  if (!search || !filter || !reset || !count || !empty || !results || !resultList) return;

  const items = [...main.querySelectorAll('.paper-item')];
  const sections = [...main.querySelectorAll('.papers-section')];
  const tierHeaders = [...main.querySelectorAll('.tier-header')];
  const subsectionHeaders = [...main.querySelectorAll('.subsection-header')];
  const tierNames = new Map();
  const sectionNames = new Map();
  const tierSections = new Map();

  let currentTier = '';
  let currentSubsection = '';
  let tierIndex = 0;
  let subsectionIndex = 0;
  let sectionIndex = 0;

  [...main.children].forEach((element) => {
    if (element.classList.contains('tier-header')) {
      currentTier = `tier-${++tierIndex}`;
      currentSubsection = '';
      element.dataset.paperTier = currentTier;
      tierNames.set(currentTier, element.querySelector('h2')?.textContent.trim() || `Field ${tierIndex}`);
      tierSections.set(currentTier, []);
      return;
    }

    if (element.classList.contains('subsection-header')) {
      currentSubsection = `subsection-${++subsectionIndex}`;
      element.dataset.paperTier = currentTier;
      element.dataset.paperSubsection = currentSubsection;
      return;
    }

    if (element.classList.contains('papers-section')) {
      const section = `section-${++sectionIndex}`;
      element.dataset.paperTier = currentTier;
      element.dataset.paperSubsection = currentSubsection;
      element.dataset.paperSection = section;
      sectionNames.set(section, element.querySelector('.section-header h2')?.textContent.trim() || `Series ${sectionIndex}`);
      tierSections.get(currentTier)?.push(section);

      element.querySelectorAll('.paper-item').forEach((item) => {
        item.dataset.paperTier = currentTier;
        item.dataset.paperSubsection = currentSubsection;
        item.dataset.paperSection = section;
      });
    }
  });

  function normalize(value) {
    return value
      .normalize('NFKD')
      .replace(/\p{M}/gu, '')
      .toLocaleLowerCase()
      .replace(/[‐‑‒–—―−_\\/]+/g, ' ')
      .replace(/[^\p{L}\p{N}]+/gu, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function textOf(item, selector) {
    return item.querySelector(selector)?.textContent.trim() || '';
  }

  const paperIndex = items.map((item, sourceIndex) => {
    const raw = {
      title: textOf(item, '.paper-title'),
      code: textOf(item, '.paper-num'),
      summary: textOf(item, '.paper-subtitle'),
      doi: textOf(item, '.doi')
    };
    const fields = Object.fromEntries(Object.entries(raw).map(([key, value]) => [key, normalize(value)]));

    return {
      item,
      sourceIndex,
      href: item.querySelector('.paper-title a')?.getAttribute('href') || `paper-${sourceIndex}`,
      raw,
      fields,
      all: Object.values(fields).join(' ')
    };
  });

  tierNames.forEach((name, tier) => {
    const group = document.createElement('optgroup');
    group.label = name;

    const allInTier = document.createElement('option');
    allInTier.value = `tier:${tier}`;
    allInTier.textContent = 'All papers in this field';
    group.append(allInTier);

    tierSections.get(tier)?.forEach((section) => {
      const option = document.createElement('option');
      option.value = `section:${section}`;
      option.textContent = sectionNames.get(section);
      group.append(option);
    });

    filter.append(group);
  });

  function matchesFilter(item, selectedFilter) {
    if (!selectedFilter) return true;
    const [type, value] = selectedFilter.split(':');
    if (type === 'tier') return item.dataset.paperTier === value;
    if (type === 'section') return item.dataset.paperSection === value;
    return true;
  }

  function scorePaper(paper, query, tokens) {
    if (!tokens.every((token) => paper.all.includes(token))) return null;

    const { title, code, summary, doi } = paper.fields;
    let score = 0;

    if (title === query) score += 1000;
    else if (title.startsWith(query)) score += 650;
    else if (title.includes(query)) score += 500;

    if (code === query) score += 900;
    else if (code.includes(query)) score += 400;

    if (doi.includes(query)) score += 350;
    if (summary.includes(query)) score += 120;

    tokens.forEach((token) => {
      if (title.includes(token)) score += 60;
      if (code.includes(token)) score += 50;
      if (doi.includes(token)) score += 40;
      if (summary.includes(token)) score += 10;
    });

    score += Math.max(0, 40 - title.length / 4);

    const matchedFields = [];
    if (tokens.some((token) => title.includes(token))) matchedFields.push('title');
    if (tokens.some((token) => code.includes(token))) matchedFields.push('paper number');
    if (tokens.some((token) => summary.includes(token))) matchedFields.push('summary');
    if (tokens.some((token) => doi.includes(token))) matchedFields.push('DOI');

    return { paper, score, matchedFields };
  }

  function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function markMatches(root, tokens) {
    const visibleTokens = tokens
      .filter((token) => token.length > 1 || /[^\x00-\x7F]/.test(token))
      .sort((a, b) => b.length - a.length);
    if (!visibleTokens.length) return;

    const pattern = new RegExp(`(${visibleTokens.map(escapeRegExp).join('|')})`, 'giu');
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        if (node.parentElement?.closest('.paper-match')) return NodeFilter.FILTER_REJECT;
        pattern.lastIndex = 0;
        return pattern.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);

    textNodes.forEach((node) => {
      pattern.lastIndex = 0;
      const fragment = document.createDocumentFragment();
      let lastIndex = 0;

      node.nodeValue.replace(pattern, (match, _group, offset) => {
        fragment.append(node.nodeValue.slice(lastIndex, offset));
        const mark = document.createElement('mark');
        mark.textContent = match;
        fragment.append(mark);
        lastIndex = offset + match.length;
        return match;
      });

      fragment.append(node.nodeValue.slice(lastIndex));
      node.replaceWith(fragment);
    });
  }

  function renderSearchResults(matches, tokens) {
    const fragment = document.createDocumentFragment();

    matches.forEach(({ paper, matchedFields }) => {
      const clone = paper.item.cloneNode(true);
      clone.hidden = false;
      clone.classList.add('paper-search-result');
      delete clone.dataset.paperTier;
      delete clone.dataset.paperSubsection;
      delete clone.dataset.paperSection;
      markMatches(clone, tokens);

      const context = document.createElement('div');
      context.className = 'paper-match';

      const fieldName = document.createElement('span');
      fieldName.className = 'paper-match-field';
      fieldName.textContent = sectionNames.get(paper.item.dataset.paperSection)
        || tierNames.get(paper.item.dataset.paperTier)
        || 'Paper library';
      context.append(fieldName);

      const matchedIn = document.createElement('span');
      matchedIn.textContent = `Matched in ${matchedFields.join(', ')}`;
      context.append(matchedIn);

      clone.querySelector('.paper-info')?.prepend(context);
      fragment.append(clone);
    });

    resultList.replaceChildren(fragment);
  }

  function hasVisiblePaper(element) {
    const tier = element.dataset.paperTier;
    const subsection = element.dataset.paperSubsection;
    return items.some((item) => {
      if (item.hidden || item.dataset.paperTier !== tier) return false;
      return !subsection || item.dataset.paperSubsection === subsection;
    });
  }

  function showOriginalLibrary(selectedFilter) {
    items.forEach((item) => {
      item.hidden = !matchesFilter(item, selectedFilter);
    });

    sections.forEach((section) => {
      section.hidden = !section.querySelector('.paper-item:not([hidden])');
    });

    tierHeaders.forEach((header) => {
      header.hidden = Boolean(selectedFilter) && !hasVisiblePaper(header);
    });

    subsectionHeaders.forEach((header) => {
      header.hidden = Boolean(selectedFilter) && !hasVisiblePaper(header);
    });
  }

  function hideOriginalLibrary() {
    sections.forEach((section) => { section.hidden = true; });
    tierHeaders.forEach((header) => { header.hidden = true; });
    subsectionHeaders.forEach((header) => { header.hidden = true; });
  }

  function updateUrl(rawQuery, selectedFilter) {
    const url = new URL(window.location.href);
    if (rawQuery) url.searchParams.set('q', rawQuery);
    else url.searchParams.delete('q');
    if (selectedFilter) url.searchParams.set('filter', selectedFilter);
    else url.searchParams.delete('filter');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function updateResults() {
    const rawQuery = search.value.trim();
    const query = normalize(rawQuery);
    const tokens = [...new Set(query.split(' ').filter(Boolean))];
    const selectedFilter = filter.value;
    const isFiltered = Boolean(query || selectedFilter);
    let visible = 0;

    if (query) {
      const rankedMatches = paperIndex
        .filter(({ item }) => matchesFilter(item, selectedFilter))
        .map((paper) => scorePaper(paper, query, tokens))
        .filter(Boolean)
        .sort((a, b) => b.score - a.score || a.paper.sourceIndex - b.paper.sourceIndex);
      const seenPapers = new Set();
      const matches = rankedMatches.filter(({ paper }) => {
        if (seenPapers.has(paper.href)) return false;
        seenPapers.add(paper.href);
        return true;
      });

      visible = matches.length;
      hideOriginalLibrary();
      renderSearchResults(matches, tokens);
      results.hidden = visible === 0;
      count.textContent = `${visible} matches · ranked by relevance`;
    } else {
      resultList.replaceChildren();
      results.hidden = true;
      showOriginalLibrary(selectedFilter);
      visible = items.filter((item) => !item.hidden).length;
      count.textContent = selectedFilter ? `${visible} of ${items.length} papers in this selection` : `${items.length} papers`;
    }

    reset.hidden = !isFiltered;
    empty.hidden = visible !== 0;
    updateUrl(rawQuery, selectedFilter);
  }

  const initialParams = new URLSearchParams(window.location.search);
  search.value = initialParams.get('q') || '';
  const initialFilter = initialParams.get('filter') || '';
  if ([...filter.options].some((option) => option.value === initialFilter)) {
    filter.value = initialFilter;
  }

  search.addEventListener('input', updateResults);
  filter.addEventListener('change', updateResults);
  reset.addEventListener('click', () => {
    search.value = '';
    filter.value = '';
    updateResults();
    search.focus();
  });

  document.addEventListener('keydown', (event) => {
    const target = event.target;
    const isTyping = target instanceof HTMLInputElement
      || target instanceof HTMLTextAreaElement
      || target instanceof HTMLSelectElement
      || target?.isContentEditable;

    if (event.key === '/' && !isTyping && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      search.focus();
    }

    if (event.key === 'Escape' && document.activeElement === search && search.value) {
      search.value = '';
      updateResults();
    }
  });

  library.hidden = false;
  updateResults();
})();
