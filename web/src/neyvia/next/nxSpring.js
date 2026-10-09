// Spring presets for Motion (motion/react), matching the CSS springs in
// nxTokens.css: snappy = small UI feedback (a selection moving), settle =
// panels and larger moves. visualDuration is how long the move looks; bounce
// stays low so nothing wobbles. MotionConfig in NxShell turns them off when
// Windows or Settings > Look asks for reduced motion.
export const SPRING = {
  snappy: { type: "spring", visualDuration: 0.22, bounce: 0.14 },
  settle: { type: "spring", visualDuration: 0.32, bounce: 0.1 },
};
