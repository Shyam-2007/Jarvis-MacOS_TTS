/**
 * Captions — what JARVIS heard and what he said, as two lines under the orb.
 *
 * Text only ever goes in through `textContent`: both lines carry arbitrary
 * recogniser and LLM output.
 *
 * What was heard is NOT shown the moment the recogniser finalises it. The
 * server decides whether a transcript is a new turn or his own voice coming
 * back through the microphone, and the page cannot tell the two apart. So a
 * final transcript is held, and only committed to the "you" line when the
 * server answers with `thinking` — i.e. it took it as a turn. Echo never
 * reaches the screen.
 */

const FADE_AFTER_MS = 12_000;
const INTERIM_STALE_MS = 2_500;

export interface Captions {
  /** A live partial from the recogniser. Shown faint, only while listening. */
  interim(text: string, listening: boolean): void;
  /** A final transcript. Held until the server confirms it as a turn. */
  heard(text: string): void;
  /** The server started thinking: commit what was heard, clear his line. */
  turnStarted(): void;
  /** A chunk of what he is saying (one sentence-ish). A new `utt` starts a
   *  new line; no `utt` (a chunk TTS could not voice) continues the current. */
  spoke(text: string, utt?: number): void;
  /** Keep the captions up while busy; let them fade once idle. */
  setBusy(busy: boolean): void;
}

export function createCaptions(): Captions {
  const root = document.createElement("div");
  root.id = "captions";
  root.setAttribute("aria-live", "polite");

  const you = document.createElement("div");
  you.className = "caption caption--you";
  const jarvis = document.createElement("div");
  jarvis.className = "caption caption--jarvis";
  root.append(you, jarvis);
  document.body.appendChild(root);

  let pending = "";
  let currentUtt: number | null = null;
  let busy = false;
  let fadeTimer: number | undefined;
  let interimTimer: number | undefined;

  function show() {
    root.classList.remove("is-faded");
    window.clearTimeout(fadeTimer);
    if (!busy) fadeTimer = window.setTimeout(() => root.classList.add("is-faded"), FADE_AFTER_MS);
  }

  function clearInterim() {
    if (you.classList.contains("is-interim")) {
      you.textContent = "";
      you.classList.remove("is-interim");
    }
  }

  return {
    interim(text, listening) {
      if (!listening || !text.trim()) return;
      jarvis.textContent = "";
      you.textContent = text;
      you.classList.add("is-interim");
      show();
      window.clearTimeout(interimTimer);
      interimTimer = window.setTimeout(clearInterim, INTERIM_STALE_MS);
    },

    heard(text) {
      pending = text.trim();
    },

    turnStarted() {
      window.clearTimeout(interimTimer);
      you.classList.remove("is-interim");
      if (pending) {
        you.textContent = pending;
        pending = "";
      } else {
        clearInterim();
      }
      jarvis.textContent = "";
      currentUtt = null;
      show();
    },

    spoke(text, utt) {
      const t = text.trim();
      if (!t) return;
      if (utt !== undefined && utt !== currentUtt) {
        currentUtt = utt;
        jarvis.textContent = t;
      } else {
        jarvis.textContent = `${jarvis.textContent} ${t}`;
      }
      clearInterim();
      show();
    },

    setBusy(b) {
      busy = b;
      window.clearTimeout(fadeTimer);
      // Going idle starts the fade clock; it never brings old captions back.
      if (!b && !root.classList.contains("is-faded")) {
        fadeTimer = window.setTimeout(() => root.classList.add("is-faded"), FADE_AFTER_MS);
      }
    },
  };
}
