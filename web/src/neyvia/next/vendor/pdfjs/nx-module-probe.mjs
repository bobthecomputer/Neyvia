// Answers only when this engine runs workers as ES modules (pdf.js needs that).
postMessage(typeof import.meta === "object" ? "nx-module-worker" : "classic");
