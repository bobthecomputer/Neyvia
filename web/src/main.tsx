import { ensureBasePack } from "./basePackGate.js";

// Importing the workspace starts backend reads. Bootstrap must finish first.
void ensureBasePack().then(() => import("./workspace"));
