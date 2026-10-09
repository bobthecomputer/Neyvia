import { createContext, useContext } from "react";

// The size of the window an app is drawn in (NxPlacement). An app placed in the side panel or a
// bubble is narrow on a wide screen: apps that switch to a compact layout read this as well as the
// viewport's phone query. Outside a window (or in older screens) it says "not compact".

export const COMPACT_PX = 640;
export const SurfaceSize = createContext({ width: Infinity, height: Infinity, compact: false, placement: "main" });
/** { width, height, compact, placement } of the window this app is drawn in. */
export const useSurfaceSize = () => useContext(SurfaceSize);
