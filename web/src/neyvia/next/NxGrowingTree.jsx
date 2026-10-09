import "./nxTree.css";

// The growing tree (nxTree.css): Neyvia's working animation. `growing` loops
// the growth; without it the tree stands still, fully grown. The startup
// splash in web/index.html draws the same markup by hand.
export function NxGrowingTree({ size = 20, growing = true, className = "" }) {
  return (
    <svg className={`ny-tree${growing ? " is-growing" : ""}${className ? ` ${className}` : ""}`} width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <circle className="ny-tree-sun" cx="23" cy="8.5" r="5" />
      <g className="ny-tree-crown">
        <path className="ny-tree-ground" d="M5 28.6Q16 26.4 27 28.6" />
        <path className="ny-tree-trunk" d="M14.6 28.4C15.3 25.4 15.3 21.6 15.1 18.6h1.8c-.2 3 -.2 6.8.5 9.8z" />
        <path className="ny-tree-branch is-left" d="M15.6 22.2C14 20.4 11.8 19.2 9.4 18.8" />
        <path className="ny-tree-branch is-right" d="M16.4 22.2C18 20.4 20.2 19.2 22.6 18.8" />
        <path className="ny-tree-branch is-mid" d="M16 19c-.1-2.4 0-4.6 0-6.6" />
        <circle className="ny-tree-leaf" cx="9.6" cy="16.6" r="3.3" />
        <circle className="ny-tree-leaf" cx="22.4" cy="16.6" r="3.3" />
        <circle className="ny-tree-leaf" cx="12.4" cy="12.4" r="3.8" />
        <circle className="ny-tree-leaf" cx="19.6" cy="12.4" r="3.8" />
        <circle className="ny-tree-leaf" cx="16" cy="9.4" r="4.2" />
      </g>
    </svg>
  );
}
