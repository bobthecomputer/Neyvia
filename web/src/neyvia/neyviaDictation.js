export const DICTATION_ERRORS = {
  "not-allowed": "Microphone access was denied. Allow the microphone in your browser’s site settings, then try again.",
  "service-not-allowed": "This browser cannot use its speech service. Open this app in Chrome, or use Windows dictation (Win + H) in the message field.",
  "audio-capture": "No microphone is available. Connect one and check your system input settings.",
  "network": "The speech service could not connect. Check your connection and try again.",
  "no-speech": "No speech was detected. Try again when you are ready.",
  "language-not-supported": "This speech service does not support the selected language. Choose another language.",
};

// One capture per click. Final segments are committed once; interim text is preview only.
export function createDictation(Recognition, { language, onText, onState }) {
  if (!Recognition) throw new Error("Speech recognition is unavailable in this browser. Open this app in Chrome, or focus the message field and press Win + H on Windows.");
  const recognition = new Recognition();
  let disposed = false;
  let failed = false;
  const committed = new Set();
  recognition.lang = language;
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.onstart = () => !disposed && onState({ status: "listening", message: "Listening… speak, then select Stop." });
  recognition.onresult = event => {
    if (disposed) return;
    const interim = [];
    for (let index = event.resultIndex; index < event.results.length; index++) {
      const result = event.results[index];
      const text = String(result[0]?.transcript || "").trim();
      if (result.isFinal && !committed.has(index)) {
        committed.add(index);
        if (text) onText(text);
      } else if (!result.isFinal && text) interim.push(text);
    }
    onState({ status: "listening", message: interim.join(" ") || "Listening… speak, then select Stop." });
  };
  recognition.onerror = event => {
    if (disposed || event.error === "aborted") return;
    failed = true;
    onState({ status: "error", message: DICTATION_ERRORS[event.error] || "Dictation stopped unexpectedly. Try again." });
  };
  recognition.onend = () => !disposed && !failed && onState({ status: "idle", message: committed.size ? "Dictation added to your draft. Review it before sending." : "Dictation ended. No text was added." });
  return {
    start() { onState({ status: "starting", message: "Starting microphone… allow access if prompted." }); recognition.start(); },
    stop() { recognition.stop(); },
    dispose() { disposed = true; recognition.onstart = recognition.onresult = recognition.onerror = recognition.onend = null; recognition.abort(); },
  };
}
