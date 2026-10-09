/* HTML drag data store for semantic engines that omit this browser API. */
(() => {
  if(typeof globalThis.DataTransfer!=='function'){
    globalThis.DataTransfer=class DataTransfer{
      constructor(){this._data=new Map();this.dropEffect='none';this.effectAllowed='uninitialized';this.files=[];}
      setData(type,value){this._data.set(String(type).toLowerCase(),String(value));}
      getData(type){return this._data.get(String(type).toLowerCase())||'';}
      clearData(type){if(type===undefined)this._data.clear();else this._data.delete(String(type).toLowerCase());}
      get types(){return Array.from(this._data.keys());}
      setDragImage(element,x,y){this._dragImage={element,x:Number(x),y:Number(y)};}
    };
  }
  if(typeof globalThis.DragEvent!=='function')globalThis.DragEvent=class DragEvent extends MouseEvent{
    constructor(type,init={}){super(type,init);this.dataTransfer=init.dataTransfer||null;}
  };
})();
