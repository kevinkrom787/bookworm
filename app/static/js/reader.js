/**
 * Atlas Reader — pagination engine + word interaction
 *
 * Flow:
 *   1. window.ATLAS.words arrives from the server (plain text word array)
 *   2. buildDOM() wraps each word in a <span class="word">
 *   3. paginate() measures which spans overflow the viewport → builds page index
 *   4. showPage() renders the correct words for the current page
 *   5. Tap on word → fetchDefinition() → showPopover()
 *   6. Tap left/right zones → prevPage() / nextPage()
 *
 * No external dependencies.
 */

"use strict";

// ── State ────────────────────────────────────────────────────────────────────
const state = {
  words: [],        // [{text, domEl}] — one entry per word
  pages: [],        // [{start, end}] — index ranges for each page
  currentPage: 0,
  fontSize: window.ATLAS?.fontSize || 20,
  isTurning: false,
};

// Last word-lookup data — used when saving to flashcards
let _lastVocabData = null;

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  const words = window.ATLAS?.words || [];
  if (!words.length) return;

  applyFontSize(state.fontSize);
  _saveCurrentBook();
  buildDOM(words, window.ATLAS?.paragraphs || []);
  // Wait two frames: first for DOM to paint, second for layout to settle
  requestAnimationFrame(() => requestAnimationFrame(() => {
    paginate();

    // Read saved word index BEFORE showPage(0) can overwrite it
    const startPage = _savedPageIndex();

    // skipSave=true on the initial render so we don't clobber the stored position
    showPage(startPage, "none", true);
    // Loading indicator was already removed by buildDOM()
  }));

  bindControls();
});

// ── DOM construction ─────────────────────────────────────────────────────────
function buildDOM(words, paragraphs) {
  const content = document.getElementById("readerContent");
  document.getElementById("readerLoading")?.remove();

  // Fallback: if no paragraph data, treat entire chapter as one paragraph
  const paras = (paragraphs && paragraphs.length > 0)
    ? paragraphs
    : (words.length > 0 ? [[0, words.length - 1]] : []);

  const fragment = document.createDocumentFragment();

  paras.forEach(([start, end]) => {
    const p = document.createElement("p");
    p.className = "reading-para";

    for (let i = start; i <= end; i++) {
      if (i >= words.length) break;
      const span = document.createElement("span");
      span.className = "word";
      span.dataset.index = i;
      span.textContent = words[i];
      span.addEventListener("pointerdown", onWordTap, { passive: true });
      p.appendChild(span);
      if (i < end) p.appendChild(document.createTextNode(" "));
      state.words.push({ text: words[i], domEl: span });
    }

    fragment.appendChild(p);
  });

  content.appendChild(fragment);

  // Progress bar (position:absolute — doesn't affect text flow)
  const bar = document.createElement("div");
  bar.className = "reader-progress";
  bar.id = "readerProgress";
  bar.style.width = "0%";
  content.prepend(bar);
}

// ── Pagination ────────────────────────────────────────────────────────────────
function paginate() {
  const content = document.getElementById("readerContent");
  const stage   = document.getElementById("readerStage");

  const contentStyle  = getComputedStyle(content);
  const paddingTop    = parseFloat(contentStyle.paddingTop);
  const paddingBottom = parseFloat(contentStyle.paddingBottom);
  const maxHeight     = stage.clientHeight - paddingTop - paddingBottom;

  const measure = content.cloneNode(false);
  measure.style.cssText =
    `position:absolute;visibility:hidden;pointer-events:none;top:0;left:0;` +
    `width:${content.clientWidth}px;max-height:none;overflow:visible;` +
    `padding:${paddingTop}px ${contentStyle.paddingRight} ${paddingBottom}px ${contentStyle.paddingLeft};`;

  // Build measurement DOM with <p> structure so paragraph margins are included
  // in the height calculation. All DOM writes happen before any reads — one reflow.
  const atlasParagraphs = (window.ATLAS?.paragraphs?.length > 0)
    ? window.ATLAS.paragraphs
    : (state.words.length > 0 ? [[0, state.words.length - 1]] : []);

  const spans = new Array(state.words.length);  // indexed by word position
  const frag  = document.createDocumentFragment();

  atlasParagraphs.forEach(([paraStart, paraEnd]) => {
    const p = document.createElement("p");
    p.className = "reading-para";
    for (let i = paraStart; i <= paraEnd && i < state.words.length; i++) {
      const span = document.createElement("span");
      span.className = "word";
      span.textContent = state.words[i].text + " ";
      p.appendChild(span);
      spans[i] = span;
    }
    frag.appendChild(p);
  });

  measure.appendChild(frag);
  document.body.appendChild(measure);

  // Read all rects in one sequential pass — no DOM writes between reads,
  // so the browser reuses the single computed layout for all measurements.
  state.pages = [];
  let pageStart = 0;
  let pageTop   = null;

  spans.forEach((span, i) => {
    if (!span) return;
    const rect = span.getBoundingClientRect();
    if (pageTop === null) pageTop = rect.top;

    if (rect.bottom - pageTop > maxHeight && i > pageStart) {
      state.pages.push({ start: pageStart, end: i - 1 });
      pageStart = i;
      pageTop   = rect.top;
    }
  });

  state.pages.push({ start: pageStart, end: state.words.length - 1 });
  document.body.removeChild(measure);
}

// ── Render page ───────────────────────────────────────────────────────────────
function showPage(pageIndex, direction = "none", skipSave = false) {
  if (pageIndex < 0 || pageIndex >= state.pages.length) return;

  const content = document.getElementById("readerContent");
  const { start, end } = state.pages[pageIndex];

  // Animate out
  if (direction !== "none" && !state.isTurning) {
    state.isTurning = true;
    const outClass = direction === "next" ? "turning-next" : "turning-prev";
    content.classList.add(outClass);
    setTimeout(() => {
      content.classList.remove(outClass);
      _renderWords(start, end);
      content.classList.add("fading-in");
      setTimeout(() => {
        content.classList.remove("fading-in");
        state.isTurning = false;
      }, 140);
    }, 140);
  } else {
    _renderWords(start, end);
  }

  state.currentPage = pageIndex;
  updateUI();
  if (!skipSave) savePosition();
}

function _renderWords(start, end) {
  // Words now live inside <p class="reading-para"> elements.
  // Strategy:
  //   • Paragraphs entirely outside [start, end] → display:none  (fast path)
  //   • Paragraphs fully inside [start, end]     → display:"", all words shown (fast path)
  //   • Paragraphs that straddle a boundary      → word-level toggle
  const content = document.getElementById("readerContent");

  content.querySelectorAll(".reading-para").forEach(para => {
    const spans = para.querySelectorAll(".word");
    if (!spans.length) { para.style.display = "none"; return; }

    const firstIdx = parseInt(spans[0].dataset.index, 10);
    const lastIdx  = parseInt(spans[spans.length - 1].dataset.index, 10);

    // Fast path: paragraph entirely outside visible range
    if (lastIdx < start || firstIdx > end) {
      para.style.display = "none";
      return;
    }

    para.style.display = "";

    // Fast path: paragraph fully inside visible range
    if (firstIdx >= start && lastIdx <= end) {
      spans.forEach(s => { s.style.display = "inline"; });
      para.childNodes.forEach(node => {
        if (node.nodeType === Node.TEXT_NODE) node.textContent = " ";
      });
      return;
    }

    // Straddles a boundary — toggle word by word
    para.childNodes.forEach(node => {
      if (node.nodeType === Node.ELEMENT_NODE && node.classList.contains("word")) {
        const idx = parseInt(node.dataset.index, 10);
        node.style.display = (idx >= start && idx <= end) ? "inline" : "none";
      } else if (node.nodeType === Node.TEXT_NODE) {
        const prev = node.previousSibling;
        if (prev && prev.classList?.contains("word")) {
          const prevIdx = parseInt(prev.dataset.index, 10);
          node.textContent = (prevIdx >= start && prevIdx < end) ? " " : "";
        }
      }
    });
  });
}

// ── Navigation ────────────────────────────────────────────────────────────────
function nextPage() {
  if (state.isTurning) return;
  if (state.currentPage < state.pages.length - 1) {
    showPage(state.currentPage + 1, "next");
  } else {
    navigateChapter(1);
  }
}

function prevPage() {
  if (state.isTurning) return;
  if (state.currentPage > 0) {
    showPage(state.currentPage - 1, "prev");
  } else {
    navigateChapter(-1);
  }
}

function navigateChapter(delta) {
  const atlas  = window.ATLAS;
  const newIdx = atlas.chapterIndex + delta;
  if (newIdx < 0 || newIdx >= atlas.totalChapters) return;
  window.location.href =
    `/read/${atlas.bookId}?chapter=${newIdx}&band=${atlas.ageBand}&font_size=${state.fontSize}&theme=${atlas.theme}`;
}

// ── Font size ─────────────────────────────────────────────────────────────────
function applyFontSize(size) {
  size = Math.max(14, Math.min(size, 36));
  state.fontSize = size;
  const content = document.getElementById("readerContent");
  if (content) content.style.fontSize = size + "px";
}

function changeFontSize(delta) {
  // Remember the first word of the current page so we can restore position
  const anchorWord = state.pages[state.currentPage]?.start ?? 0;

  applyFontSize(state.fontSize + delta);

  if (state.words.length) {
    // Wait one frame so the browser reflows the new font size before we measure
    requestAnimationFrame(() => {
      paginate();
      // Find the page that now contains our anchor word
      const targetPage = Math.max(0, state.pages.findIndex(p => p.end >= anchorWord));
      showPage(targetPage, "none", true); // skipSave=true — don't overwrite stored pos
    });
  }
}

// ── Theme toggle ──────────────────────────────────────────────────────────────
const THEMES = ["light", "dark", "redlight"];
let themeIndex = THEMES.indexOf(window.ATLAS?.theme || "light");

function toggleTheme() {
  themeIndex = (themeIndex + 1) % THEMES.length;
  const theme = THEMES[themeIndex];
  document.documentElement.dataset.theme = theme;          // apply globally on <html>
  document.getElementById("readerShell").dataset.theme = theme;
  window.ATLAS.theme = theme;
  try { localStorage.setItem("atlas:theme", theme); } catch(e) {}  // persist across sessions
}

// ── Reading position persistence ──────────────────────────────────────────────
// Keyed by book + chapter so each chapter remembers its own position.
// Word index is used (not page number) because page numbers shift when
// font size changes — word index is always stable.
// DB migration path: replace localStorage calls with an API write.

function _posKey()     { return `atlas:pos:${window.ATLAS.bookId}:${window.ATLAS.chapterIndex}`; }
function _chapterKey() { return `atlas:chapter:${window.ATLAS.bookId}`; }

function _saveCurrentBook() {
  const a = window.ATLAS;
  try {
    localStorage.setItem("atlas:current_book", JSON.stringify({
      id:            a.bookId,
      title:         a.bookTitle,
      author:        a.bookAuthor,
      cover:         a.bookCover,
      chapter:       a.chapterIndex,
      chapterTitle:  a.chapterTitle,
      totalChapters: a.totalChapters,
    }));
    // Update streak — mark today as a reading day
    const today = new Date().toDateString();
    localStorage.setItem("atlas:last_read_date", today);
  } catch(e) {}
}

function savePosition() {
  const firstWord = state.pages[state.currentPage]?.start ?? 0;
  try {
    localStorage.setItem(_posKey(),     String(firstWord));
    localStorage.setItem(_chapterKey(), String(window.ATLAS.chapterIndex));
  } catch (e) { /* storage full or private mode — ignore */ }
}

function _savedPageIndex() {
  // Returns the page index for the stored word position, or 0 if none saved.
  // Called before showPage() so we never overwrite a good saved position.
  try {
    const savedWord = parseInt(localStorage.getItem(_posKey()) || "0", 10);
    if (savedWord <= 0) return 0;
    const page = state.pages.findIndex(p => p.end >= savedWord);
    return page >= 0 ? page : 0;
  } catch (e) {
    return 0;
  }
}

// ── UI update ─────────────────────────────────────────────────────────────────
function updateUI() {
  const indicator = document.getElementById("pageIndicator");
  if (indicator) {
    indicator.textContent = `${state.currentPage + 1} / ${state.pages.length}`;
  }

  const progress = document.getElementById("readerProgress");
  if (progress && state.pages.length > 0) {
    const pct = ((state.currentPage + 1) / state.pages.length) * 100;
    progress.style.width = pct + "%";
  }

  // Prev/next chapter buttons
  const atlas = window.ATLAS;
  const prevChBtn = document.getElementById("prevChapterBtn");
  const nextChBtn = document.getElementById("nextChapterBtn");
  if (prevChBtn) prevChBtn.disabled = atlas.chapterIndex <= 0;
  if (nextChBtn) nextChBtn.disabled = atlas.chapterIndex >= atlas.totalChapters - 1;
}

// ── Control bindings ─────────────────────────────────────────────────────────
function bindControls() {
  // Page navigation buttons
  document.getElementById("prevPageBtn")?.addEventListener("click", prevPage);
  document.getElementById("nextPageBtn")?.addEventListener("click", nextPage);
  document.getElementById("prevChapterBtn")?.addEventListener("click", () => navigateChapter(-1));
  document.getElementById("nextChapterBtn")?.addEventListener("click", () => navigateChapter(1));

  // Tap zones (left/right sides of reading area)
  document.getElementById("tapLeft")?.addEventListener("click", prevPage);
  document.getElementById("tapRight")?.addEventListener("click", nextPage);

  // Font size
  document.getElementById("fontDecBtn")?.addEventListener("click", () => changeFontSize(-2));
  document.getElementById("fontIncBtn")?.addEventListener("click", () => changeFontSize(2));

  // Theme
  document.getElementById("themeBtn")?.addEventListener("click", toggleTheme);

  // Keyboard (for development on Mac)
  document.addEventListener("keydown", e => {
    if (e.key === "ArrowRight" || e.key === "PageDown") nextPage();
    if (e.key === "ArrowLeft"  || e.key === "PageUp")   prevPage();
  });

  // Swipe gestures
  bindSwipe();

  // Popover close
  document.getElementById("popoverClose")?.addEventListener("click", closePopover);
  document.getElementById("popoverBackdrop")?.addEventListener("click", closePopover);

  // Add to vocabulary flashcard
  document.getElementById("addVocabBtn")?.addEventListener("click", async () => {
    const word = document.getElementById("popoverWord")?.textContent.trim();
    if (!word) return;

    const btn = document.getElementById("addVocabBtn");
    btn.disabled = true;
    btn.textContent = "Saving…";

    const atlas      = window.ATLAS || {};
    const imgEl      = document.getElementById("popoverImg");
    const imageUrl   = (imgEl && !imgEl.closest("[hidden]") ? imgEl.src : null)
                       || localStorage.getItem(`atlas:vocab_image:${word}`)
                       || null;
    const definition     = _lastVocabData?.definitions?.[0]?.definition || "";
    const exampleSentence = _lastVocabData?.definitions?.[0]?.example || "";
    const phonetic       = _lastVocabData?.phonetic || "";

    try {
      const resp = await fetch("/api/vocab/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          word,
          phonetic,
          definition,
          example_sentence: exampleSentence,
          image_url: imageUrl,
          source_book:    atlas.bookTitle    || null,
          source_chapter: atlas.chapterTitle || null,
        }),
      });
      const result = await resp.json();
      btn.textContent = result.duplicate ? "Already saved ✓" : "Saved! ✓";
    } catch (e) {
      btn.textContent = "Couldn't save";
      btn.disabled = false;
      return;
    }

    setTimeout(closePopover, 700);
  });

  // Image search — "Change image" button (visible when an image is shown)
  document.getElementById("changeImageBtn")?.addEventListener("click", () => {
    const word = document.getElementById("popoverWord")?.textContent.trim() || "";
    openImageSearch(word);
  });

  // Clear saved image — removes it from localStorage and hides the image wrap
  document.getElementById("clearImageBtn")?.addEventListener("click", () => {
    const word = document.getElementById("popoverWord")?.textContent.trim() || "";
    if (word) localStorage.removeItem(`atlas:vocab_image:${word}`);
    document.getElementById("popoverImage").hidden = true;
    document.getElementById("findImageBtn").hidden  = false;
    document.getElementById("imageSearchPanel").hidden = true;
  });

  // Image search — "Find an image" button (visible when no image exists)
  document.getElementById("findImageBtn")?.addEventListener("click", () => {
    const word = document.getElementById("popoverWord")?.textContent.trim() || "";
    openImageSearch(word);
  });

  // Image search form submit
  document.getElementById("imageSearchForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = document.getElementById("imageSearchInput")?.value.trim();
    if (q) runImageSearch(q);
  });
}

// ── Swipe detection ───────────────────────────────────────────────────────────
function bindSwipe() {
  let startX = 0;
  const threshold = 60; // px

  document.getElementById("readerStage")?.addEventListener("touchstart", e => {
    startX = e.touches[0].clientX;
  }, { passive: true });

  document.getElementById("readerStage")?.addEventListener("touchend", e => {
    const dx = e.changedTouches[0].clientX - startX;
    if (Math.abs(dx) > threshold) {
      dx < 0 ? nextPage() : prevPage();
    }
  }, { passive: true });
}

// ── Word tap → definition ─────────────────────────────────────────────────────
async function onWordTap(e) {
  const span = e.currentTarget;
  const rawWord = span.textContent.trim();

  // Brief visual feedback
  span.classList.add("tapped");
  setTimeout(() => span.classList.remove("tapped"), 200);

  await fetchAndShowDefinition(rawWord);
}

async function fetchAndShowDefinition(word) {
  const popover  = document.getElementById("defPopover");
  const backdrop = document.getElementById("popoverBackdrop");
  const wordEl   = document.getElementById("popoverWord");
  const phonEl   = document.getElementById("popoverPhonetic");
  const defsEl   = document.getElementById("popoverDefs");
  const imgEl    = document.getElementById("popoverImage");

  const findBtn  = document.getElementById("findImageBtn");
  const searchPanel = document.getElementById("imageSearchPanel");

  // Show immediately with loading state
  wordEl.textContent  = word;
  phonEl.innerHTML    = "";
  defsEl.innerHTML    = '<p style="color:var(--color-text-3);font-size:0.9rem">Looking up…</p>';
  imgEl.hidden        = true;
  findBtn.hidden      = true;
  searchPanel.hidden  = true;
  popover.hidden      = false;
  backdrop.hidden     = false;

  // Check localStorage for a user-chosen image first
  const savedImage = loadSavedImage(word);
  if (savedImage) {
    document.getElementById("popoverImg").src = savedImage;
    imgEl.hidden   = false;
    findBtn.hidden = true;
  }

  try {
    const resp = await fetch(`/api/vocab/define?word=${encodeURIComponent(word)}`);
    const data = await resp.json();

    // ── Image (auto or user-saved) ────────────────────────────────────
    if (!savedImage) {
      // No user choice yet — use auto-fetched image if available
      if (data.image_url) {
        document.getElementById("popoverImg").src = data.image_url;
        imgEl.hidden   = false;
        findBtn.hidden = true;
      } else {
        // No auto image — show "Find an image" button
        imgEl.hidden   = true;
        findBtn.hidden = false;
      }
    }
    // If savedImage was already set above, leave it as-is

    // ── Phonetic + audio button ───────────────────────────────────────
    if (data.phonetic || data.audio_url) {
      phonEl.innerHTML = `
        <span class="phonetic-text">${escHtml(data.phonetic || "")}</span>
        ${data.audio_url ? `
          <button class="audio-btn" id="pronAudioBtn" aria-label="Hear pronunciation" title="Hear pronunciation">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
              <path d="M15.54 8.46a5 5 0 0 1 0 7.07" stroke="currentColor" stroke-width="2" fill="none"/>
            </svg>
          </button>` : ""}
      `;

      if (data.audio_url) {
        document.getElementById("pronAudioBtn").addEventListener("click", () => {
          new Audio(data.audio_url).play().catch(() => {});
        });
      }
    } else {
      phonEl.innerHTML = "";
    }

    // ── Definitions ───────────────────────────────────────────────────
    // Cache for save-to-flashcards action
    _lastVocabData = data;

    // Re-enable the Add to Vocab button for this new word
    const addBtn = document.getElementById("addVocabBtn");
    if (addBtn) { addBtn.textContent = "+ Add to Vocabulary"; addBtn.disabled = false; }

    if (data.definitions?.length) {
      defsEl.innerHTML = data.definitions.map(d => `
        <div class="def-item">
          ${d.part_of_speech ? `<div class="def-pos">${escHtml(d.part_of_speech)}</div>` : ""}
          <div class="def-text">${escHtml(d.definition)}</div>
          ${d.example ? `<div class="def-example">"${escHtml(d.example)}"</div>` : ""}
        </div>
      `).join("");
    } else {
      defsEl.innerHTML = '<p style="color:var(--color-text-3)">No definition found.</p>';
    }

  } catch (err) {
    defsEl.innerHTML = '<p style="color:var(--color-text-3)">Could not load definition.</p>';
  }
}

function closePopover() {
  document.getElementById("defPopover").hidden      = true;
  document.getElementById("popoverBackdrop").hidden = true;
  document.getElementById("imageSearchPanel").hidden = true;
}

// ── Image search ──────────────────────────────────────────────────────────────

function openImageSearch(word) {
  const panel = document.getElementById("imageSearchPanel");
  const input = document.getElementById("imageSearchInput");
  panel.hidden = false;
  input.value  = word;  // keep input clean so user can edit it
  // Add "illustration" to the auto-search — returns cleaner, more
  // concept-driven results than photos tagged with the bare word
  runImageSearch(word + " illustration");
}

async function runImageSearch(query) {
  const grid = document.getElementById("imageSearchGrid");
  grid.innerHTML = '<p style="color:var(--color-text-3);font-size:0.85rem;padding:8px 0">Searching…</p>';

  try {
    const resp = await fetch(`/api/vocab/image-search?q=${encodeURIComponent(query)}`);
    const data = await resp.json();

    // API key not set up yet — show instructions, don't show unfiltered results
    if (data.setup_required) {
      grid.innerHTML = `
        <div style="padding:8px 0;font-size:0.82rem;color:var(--color-text-2);line-height:1.5;">
          <strong>Image search needs a free API key.</strong><br>
          This keeps images safe for kids. Two options:<br><br>
          <strong>Pixabay (easiest):</strong> Register free at
          <span style="color:var(--color-accent)">pixabay.com/api/docs</span>,
          then set <code>PIXABAY_API_KEY</code> in your environment.<br><br>
          <strong>Google:</strong> Set <code>GOOGLE_SEARCH_API_KEY</code>
          + <code>GOOGLE_SEARCH_CX</code> for Google's SafeSearch.
        </div>`;
      return;
    }

    if (!data.images?.length) {
      grid.innerHTML = '<p style="color:var(--color-text-3);font-size:0.85rem;padding:8px 0">No images found — try a different word.</p>';
      return;
    }

    grid.innerHTML = "";
    data.images.forEach(img => {
      const btn = document.createElement("button");
      btn.className   = "image-result-btn";
      btn.title       = "Use this image";
      btn.style.backgroundImage = `url(${escHtml(img.thumb)})`;
      btn.addEventListener("click", () => selectImage(img.full || img.thumb));
      grid.appendChild(btn);
    });
  } catch (e) {
    grid.innerHTML = '<p style="color:var(--color-text-3);font-size:0.85rem;padding:8px 0">Search unavailable offline.</p>';
  }
}

function selectImage(url) {
  // Show in popover immediately
  const imgWrap = document.getElementById("popoverImage");
  const imgEl   = document.getElementById("popoverImg");
  const findBtn = document.getElementById("findImageBtn");
  imgEl.src     = url;
  imgWrap.hidden = false;
  findBtn.hidden = true;

  // Persist in localStorage — migrates to DB column in schema phase
  const word = document.getElementById("popoverWord").textContent.trim();
  if (word) {
    localStorage.setItem(`atlas:vocab_image:${word}`, url);
  }

  // Collapse the search panel
  document.getElementById("imageSearchPanel").hidden = true;
}

function loadSavedImage(word) {
  // Check if user has previously chosen an image for this word
  return localStorage.getItem(`atlas:vocab_image:${word}`) || null;
}

// ── Utility ───────────────────────────────────────────────────────────────────
function escHtml(str) {
  return (str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Expose for tts.js ─────────────────────────────────────────────────────────
window.AtlasReader = {
  getWordEls: () => state.words.map(w => w.domEl),
  getPageText: () => {
    if (!state.pages.length) return "";
    const { start, end } = state.pages[state.currentPage];
    return state.words.slice(start, end + 1).map(w => w.text).join(" ");
  },
  getPageWordOffset: () => state.pages[state.currentPage]?.start ?? 0,
};
