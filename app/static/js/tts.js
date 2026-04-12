/**
 * Atlas TTS Controller
 *
 * Fetches audio from /api/tts/synthesize, plays it, and highlights
 * words in the reader as they're spoken using the word timing array.
 *
 * Word timings from the server are estimates when Kokoro is not installed
 * (stub mode). Once kokoro-onnx is installed, the same interface works
 * with real phoneme-level accuracy.
 *
 * Works with reader.js via window.AtlasReader.
 */

"use strict";

const TTS = {
  audio: null,
  timings: [],
  wordOffset: 0,    // global word index of first word on current page
  rafId: null,
  isPlaying: false,
  btn: null,
  btnLabel: null,
};

document.addEventListener("DOMContentLoaded", () => {
  TTS.btn      = document.getElementById("ttsBtn");
  TTS.btnLabel = document.getElementById("ttsBtnLabel");

  if (!TTS.btn) return;

  TTS.btn.addEventListener("click", () => {
    TTS.isPlaying ? stopTTS() : startTTS();
  });
});

// ── Start ─────────────────────────────────────────────────────────────────────
async function startTTS() {
  const reader = window.AtlasReader;
  if (!reader) return;

  const text = reader.getPageText();
  if (!text.trim()) return;

  setPlaying(true);

  try {
    const resp = await fetch("/api/tts/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    if (!resp.ok) throw new Error("TTS request failed");
    const data = await resp.json();

    // Decode base64 WAV → Blob → Audio
    const binary   = atob(data.audio_b64);
    const bytes    = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob     = new Blob([bytes], { type: "audio/wav" });
    const audioUrl = URL.createObjectURL(blob);

    TTS.timings    = data.word_timings || [];
    TTS.wordOffset = reader.getPageWordOffset();

    TTS.audio = new Audio(audioUrl);
    TTS.audio.addEventListener("ended",  () => { stopTTS(); URL.revokeObjectURL(audioUrl); });
    TTS.audio.addEventListener("error",  () => { stopTTS(); });
    TTS.audio.play();
    startHighlighting();

  } catch (err) {
    console.error("TTS error:", err);
    stopTTS();
  }
}

// ── Stop ──────────────────────────────────────────────────────────────────────
function stopTTS() {
  if (TTS.audio) {
    TTS.audio.pause();
    TTS.audio = null;
  }
  if (TTS.rafId) {
    cancelAnimationFrame(TTS.rafId);
    TTS.rafId = null;
  }
  clearHighlight();
  setPlaying(false);
}

// ── Word highlighting ─────────────────────────────────────────────────────────
function startHighlighting() {
  const tick = () => {
    if (!TTS.audio || TTS.audio.paused || TTS.audio.ended) return;

    const currentMs = TTS.audio.currentTime * 1000;

    // Find which word should be highlighted right now
    const timing = TTS.timings.find(
      t => currentMs >= t.start_ms && currentMs < t.end_ms
    );

    if (timing !== undefined) {
      highlightWord(timing.index);
    }

    TTS.rafId = requestAnimationFrame(tick);
  };

  TTS.rafId = requestAnimationFrame(tick);
}

function highlightWord(localIndex) {
  const wordEls = window.AtlasReader?.getWordEls() || [];

  // Remove previous highlight
  wordEls.forEach(el => el.classList.remove("tts-active"));

  // localIndex is relative to the page — find the right span
  const globalIndex = TTS.wordOffset + localIndex;
  const target = wordEls.find(
    el => parseInt(el.dataset.index, 10) === globalIndex
  );

  if (target) {
    target.classList.add("tts-active");
    // Scroll the word into view if it's somehow off-screen
    target.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }
}

function clearHighlight() {
  const wordEls = window.AtlasReader?.getWordEls() || [];
  wordEls.forEach(el => el.classList.remove("tts-active"));
}

// ── UI state ──────────────────────────────────────────────────────────────────
function setPlaying(playing) {
  TTS.isPlaying = playing;
  if (!TTS.btn) return;
  TTS.btn.classList.toggle("playing", playing);
  if (TTS.btnLabel) {
    TTS.btnLabel.textContent = playing ? "Stop" : "Read Aloud";
  }
}
