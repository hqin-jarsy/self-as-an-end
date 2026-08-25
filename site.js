(() => {
  const library = document.querySelector('[data-paper-library]');
  const main = document.querySelector('main');
  if (!library || !main) return;

  const search = library.querySelector('[data-paper-search]');
  const field = library.querySelector('[data-paper-field]');
  const reset = library.querySelector('[data-paper-reset]');
  const count = library.querySelector('[data-paper-count]');
  const empty = library.querySelector('[data-paper-empty]');
  const items = [...main.querySelectorAll('.paper-item')];
  const sections = [...main.querySelectorAll('.papers-section')];
  const tierHeaders = [...main.querySelectorAll('.tier-header')];
  const subsectionHeaders = [...main.querySelectorAll('.subsection-header')];
  const tierNames = new Map();

  let currentTier = '';
  let currentSubsection = '';
  let tierIndex = 0;
  let subsectionIndex = 0;

  [...main.children].forEach((element) => {
    if (element.classList.contains('tier-header')) {
      currentTier = `tier-${++tierIndex}`;
      currentSubsection = '';
      element.dataset.paperTier = currentTier;
      tierNames.set(currentTier, element.querySelector('h2')?.textContent.trim() || `Field ${tierIndex}`);
      return;
    }

    if (element.classList.contains('subsection-header')) {
      currentSubsection = `subsection-${++subsectionIndex}`;
      element.dataset.paperTier = currentTier;
      element.dataset.paperSubsection = currentSubsection;
      return;
    }

    if (element.classList.contains('papers-section')) {
      element.dataset.paperTier = currentTier;
      element.dataset.paperSubsection = currentSubsection;
      element.querySelectorAll('.paper-item').forEach((item) => {
        item.dataset.paperTier = currentTier;
        item.dataset.paperSubsection = currentSubsection;
        item.dataset.paperSearch = normalize(item.textContent);
      });
    }
  });

  tierNames.forEach((name, value) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = name;
    field.append(option);
  });

  function normalize(value) {
    return value.normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, ' ').trim();
  }

  function hasVisiblePaper(element) {
    const tier = element.dataset.paperTier;
    const subsection = element.dataset.paperSubsection;
    return items.some((item) => {
      if (item.hidden || item.dataset.paperTier !== tier) return false;
      return !subsection || item.dataset.paperSubsection === subsection;
    });
  }

  function updateResults() {
    const query = normalize(search.value);
    const selectedTier = field.value;
    const isFiltered = Boolean(query || selectedTier);
    let visible = 0;

    items.forEach((item) => {
      const matchesQuery = !query || item.dataset.paperSearch.includes(query);
      const matchesTier = !selectedTier || item.dataset.paperTier === selectedTier;
      item.hidden = !(matchesQuery && matchesTier);
      if (!item.hidden) visible += 1;
    });

    sections.forEach((section) => {
      section.hidden = !section.querySelector('.paper-item:not([hidden])');
    });

    tierHeaders.forEach((header) => {
      header.hidden = isFiltered && !hasVisiblePaper(header);
    });

    subsectionHeaders.forEach((header) => {
      header.hidden = isFiltered && !hasVisiblePaper(header);
    });

    count.textContent = isFiltered
      ? `${visible} of ${items.length} papers shown`
      : `${items.length} papers`;
    reset.hidden = !isFiltered;
    empty.hidden = visible !== 0;
  }

  search.addEventListener('input', updateResults);
  field.addEventListener('change', updateResults);
  reset.addEventListener('click', () => {
    search.value = '';
    field.value = '';
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
