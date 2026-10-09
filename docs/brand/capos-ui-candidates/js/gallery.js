/* CapOS candidate gallery interactivity */

const SURFACES = ["chat", "notebook", "lab", "orchestration", "library"];

const TUTORIAL_STEPS = [
  {
    title: "One workspace, five surfaces",
    body: "Chat, Notebook, Lab, Orchestration, and Library share one shell. Domains are packs, not permanent sidebar apps.",
    spotlight: ".capos-surfaces",
  },
  {
    title: "Artifacts become central",
    body: "When you open a PDF, scene, or dataset, the canvas owns the viewport. The agent stays contextual on the side.",
    spotlight: ".capos-canvas",
  },
  {
    title: "Plan before run",
    body: "Capability selection shows tools, models, cost, permissions, and expected proof before anything executes.",
    spotlight: "[data-action='plan']",
  },
  {
    title: "Image Playground is a tool",
    body: "Media generation stays available as a drawer tool, not a disconnected mini-app competing for navigation.",
    spotlight: "[data-action='images']",
  },
  {
    title: "Proof stays compact",
    body: "Receipts, diffs, and benchmarks live in a slim strip until you ask for full evidence.",
    spotlight: ".capos-proof",
  },
];

function qs(root, sel) {
  return root.querySelector(sel);
}

function qsa(root, sel) {
  return [...root.querySelectorAll(sel)];
}

function setSurface(shell, surfaceId) {
  qsa(shell, ".capos-surfaces button").forEach((btn) => {
    btn.setAttribute("aria-selected", String(btn.dataset.surface === surfaceId));
  });
  qsa(shell, ".surface-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.surface === surfaceId);
  });
  shell.dataset.surface = surfaceId;

  const proof = qs(shell, "[data-proof-label]");
  if (proof) {
    const labels = {
      chat: "Ready · no artifact selected",
      notebook: "PDF · native text · OCR skipped",
      lab: "Scene lineage · glTF preview cached",
      orchestration: "3 specialists · 1 waiting judgment",
      library: "14 packs installed · 2 tutorials due",
    };
    proof.textContent = labels[surfaceId] || "Ready";
  }
}

function openPlan(shell) {
  const sheet = qs(shell, ".plan-sheet");
  if (!sheet) return;
  sheet.classList.add("open");
  sheet.setAttribute("aria-hidden", "false");
}

function closePlan(shell) {
  const sheet = qs(shell, ".plan-sheet");
  if (!sheet) return;
  sheet.classList.remove("open");
  sheet.setAttribute("aria-hidden", "true");
}

function toggleImages(shell, force) {
  const drawer = qs(shell, ".tool-drawer");
  const btn = qs(shell, "[data-action='images']");
  if (!drawer || !btn) return;
  const next = typeof force === "boolean" ? force : !drawer.classList.contains("open");
  drawer.classList.toggle("open", next);
  btn.setAttribute("aria-pressed", String(next));
}

function setTutorial(shell, stepIndex) {
  const overlay = qs(shell, ".tutorial-overlay");
  const spotlight = qs(shell, ".tutorial-spotlight");
  if (!overlay) return;

  const step = TUTORIAL_STEPS[stepIndex];
  if (!step) {
    overlay.classList.remove("open");
    if (spotlight) spotlight.classList.remove("open");
    shell.dataset.tutorialStep = "";
    return;
  }

  shell.dataset.tutorialStep = String(stepIndex);
  overlay.classList.add("open");
  qs(overlay, "[data-tutorial-progress]").textContent = `${stepIndex + 1} / ${TUTORIAL_STEPS.length}`;
  qs(overlay, "[data-tutorial-title]").textContent = step.title;
  qs(overlay, "[data-tutorial-body]").textContent = step.body;

  if (spotlight && step.spotlight) {
    const target = qs(shell, step.spotlight);
    if (target) {
      const shellRect = shell.getBoundingClientRect();
      const rect = target.getBoundingClientRect();
      spotlight.style.top = `${rect.top - shellRect.top - 6}px`;
      spotlight.style.left = `${rect.left - shellRect.left - 6}px`;
      spotlight.style.width = `${rect.width + 12}px`;
      spotlight.style.height = `${rect.height + 12}px`;
      spotlight.classList.add("open");
    }
  }
}

function wireShell(shell) {
  qsa(shell, ".capos-surfaces button").forEach((btn) => {
    btn.addEventListener("click", () => setSurface(shell, btn.dataset.surface));
  });

  qsa(shell, "[data-action='plan']").forEach((btn) => {
    btn.addEventListener("click", () => openPlan(shell));
  });

  qsa(shell, "[data-action='close-plan']").forEach((btn) => {
    btn.addEventListener("click", () => closePlan(shell));
  });

  qsa(shell, "[data-action='images']").forEach((btn) => {
    btn.addEventListener("click", () => toggleImages(shell));
  });

  qsa(shell, "[data-action='close-images']").forEach((btn) => {
    btn.addEventListener("click", () => toggleImages(shell, false));
  });

  qsa(shell, "[data-action='tutorial']").forEach((btn) => {
    btn.addEventListener("click", () => setTutorial(shell, 0));
  });

  qsa(shell, "[data-action='tutorial-next']").forEach((btn) => {
    btn.addEventListener("click", () => {
      const current = Number(shell.dataset.tutorialStep || 0);
      if (current >= TUTORIAL_STEPS.length - 1) setTutorial(shell, -1);
      else setTutorial(shell, current + 1);
    });
  });

  qsa(shell, "[data-action='tutorial-back']").forEach((btn) => {
    btn.addEventListener("click", () => {
      const current = Number(shell.dataset.tutorialStep || 0);
      setTutorial(shell, Math.max(0, current - 1));
    });
  });

  qsa(shell, "[data-action='tutorial-skip']").forEach((btn) => {
    btn.addEventListener("click", () => setTutorial(shell, -1));
  });

  const plan = qs(shell, ".plan-sheet");
  if (plan) {
    plan.addEventListener("click", (event) => {
      if (event.target === plan) closePlan(shell);
    });
  }

  setSurface(shell, shell.dataset.surface || "chat");
}

function wireGalleryNav() {
  const links = qsa(document, ".gallery-nav a[href^='#']");
  const sections = links
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const id = `#${entry.target.id}`;
        links.forEach((link) => {
          link.setAttribute("aria-current", String(link.getAttribute("href") === id));
        });
      });
    },
    { rootMargin: "-35% 0px -55% 0px", threshold: 0.01 },
  );

  sections.forEach((section) => observer.observe(section));
}

function wireVariantPickers() {
  qsa(document, "[data-variant-target]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const shellId = btn.dataset.variantTarget;
      const shell = document.getElementById(shellId);
      if (!shell) return;
      if (btn.dataset.layout) shell.dataset.layout = btn.dataset.layout;
      if (btn.dataset.theme) shell.dataset.theme = btn.dataset.theme;
      qsa(btn.parentElement, "button").forEach((sibling) => {
        sibling.setAttribute("aria-pressed", String(sibling === btn));
      });
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  qsa(document, ".capos-shell").forEach(wireShell);
  wireGalleryNav();
  wireVariantPickers();
});
