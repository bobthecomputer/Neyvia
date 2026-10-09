export function EmulatedKeyboard({frameRef}) {
  const key = value => frameRef?.current?.contentWindow?.postMessage({source:"nx-studio",type:"keyboard-key",key:value},"*");
  return <div className="nx-ms-keyboard" aria-label="Emulated keyboard">
    {["qwertyuiop","asdfghjkl","zxcvbnm"].map(row=><div key={row}>{[...row].map(letter=><button type="button" key={letter} onClick={()=>key(letter)}>{letter}</button>)}</div>)}
    <div><button type="button" onClick={()=>key("Backspace")}>Delete</button><button type="button" onClick={()=>key(" ")}>Space</button><button type="button" onClick={()=>key("Enter")}>Return</button></div>
    <small>Emulated keyboard</small>
  </div>;
}
