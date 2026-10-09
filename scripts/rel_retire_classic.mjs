// One-time migration: keep only the library panels the single shell imports.
import fs from 'node:fs';
import { parse } from '@babel/parser';
import traverseModule from '@babel/traverse';
const traverse = traverseModule.default;
const update = (file, transform) => fs.writeFileSync(file, transform(fs.readFileSync(file, 'utf8')), 'utf8');

update('web/src/workspace.tsx', text => text
  .replace(/^import "\.\/neyvia\/(?!neyviaFonts)[^"]+\.css";\r?\n/gm, '')
  .replace(/^import \{ NeyviaSessionWorkspaceChrome \}[^\n]*\n/m, '')
  .replace(/\s*<NeyviaSessionWorkspaceChrome>\s*<NeyviaApp \/>\s*<\/NeyviaSessionWorkspaceChrome>/, '\n    <NeyviaApp />'));

const file = 'web/src/neyvia/NeyviaShellSurfaces.jsx';
let source = fs.readFileSync(file, 'utf8');
const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
traverse(ast, { Program(path) {
  const needed = new Set(['NeyviaNotebookSurface', 'NeyviaLabSurface', 'NeyviaLibrarySurface']);
  const keep = new Set();
  let more = true;
  while (more) {
    more = false;
    for (const name of [...needed]) {
      const binding = path.scope.getBinding(name);
      if (!binding) continue;
      const top = binding.path.findParent(p => p.parentPath === path);
      if (!top || keep.has(top.node)) continue;
      keep.add(top.node); more = true;
      top.traverse({ ReferencedIdentifier(p) {
        const dependency = p.scope.getBinding(p.node.name);
        if (dependency && dependency.scope === path.scope) needed.add(p.node.name);
      }});
    }
  }
  const chunks = [];
  for (const node of ast.program.body) {
    if (node.type === 'ImportDeclaration') {
      const selected = node.specifiers.filter(spec => needed.has(spec.local.name));
      if (!selected.length && node.specifiers.length) continue;
      const named = selected.filter(spec => spec.type === 'ImportSpecifier').map(spec => spec.imported.name === spec.local.name ? spec.local.name : `${spec.imported.name} as ${spec.local.name}`);
      const defaultName = selected.find(spec => spec.type === 'ImportDefaultSpecifier')?.local.name;
      const parts = [defaultName, named.length ? `{ ${named.join(', ')} }` : null].filter(Boolean);
      const target = node.source.value.startsWith('./') ? '../' + node.source.value.slice(2) : node.source.value;
      chunks.push(parts.length ? `import ${parts.join(', ')} from ${JSON.stringify(target)};` : `import ${JSON.stringify(target)};`);
    } else if (keep.has(node)) chunks.push(source.slice(node.start, node.end));
  }
  source = chunks.join('\n\n') + '\n';
}});
fs.writeFileSync('web/src/neyvia/next/NxLibrarySurfaces.jsx', source);

const pairs = [
  ['CLASSIC_SUITES','TOOL_SUITES'], ['CLASSIC_TITLES','TOOL_TITLES'], ['CLASSIC_LAUNCH','TOOL_LAUNCH'], ['CLASSIC_ALIASES','APP_ALIASES'],
  ['NxClassicScreen','NxToolScreen'], ['isClassicScreen','isToolScreen'], ['openClassic','openTool'], ['classicCallBackend','callToolBackend'], ['useClassicNavigation','useToolNavigation'],
  ['NxClassicScreens','NxToolScreens'], ['nxClassic.css','nxToolScreens.css'], ['nx-classic','nx-tool-screen'], ['data-classic-screen','data-tool-screen'],
  ['classic-app:', 'tool-app:'], ['classic.library.filter','library.filter']
];
for (const name of ['web/src/neyvia/next/NxClassicScreens.jsx','web/src/neyvia/next/nxClassic.css','web/src/neyvia/next/NxStage.jsx','web/src/neyvia/next/nxShellLauncher.js']) {
  update(name, text => pairs.reduce((result, [from, to]) => result.replaceAll(from, to), text));
}
fs.renameSync('web/src/neyvia/next/NxClassicScreens.jsx', 'web/src/neyvia/next/NxToolScreens.jsx');
fs.renameSync('web/src/neyvia/next/nxClassic.css', 'web/src/neyvia/next/nxToolScreens.css');
update('web/src/neyvia/next/NxToolScreens.jsx', text => text
  .replaceAll('import("../NeyviaShellSurfaces.jsx")', 'import("./NxLibrarySurfaces.jsx")')
  .replace(/\/\/ Classic panels that open[\s\S]*?function useToolNavigation/, 'function useToolNavigation')
  .replace(/os\.notify\(\{ level: "info", message: "That (?:screen|tool|action)[^\n]+classicOnce[^\n]+/g,
    'os.notify({ level: "warning", message: "This action has no screen in this build. Choose it from Apps or open a new chat." });')
  .replaceAll('classic', 'tool'));
update('web/src/neyvia/next/NxStage.jsx', text => text.replaceAll('classic', 'tool'));
update('web/src/neyvia/next/nxToolScreens.css', text => text.replaceAll('classic', 'tool'));
update('web/src/neyvia/next/nxShellLauncher.js', text => text.replace('id.slice(12)', 'id.slice(9)').replaceAll('classic', 'tool'));
console.log('Moved Notebook, Lab and Library into the single shell; removed retired routing and wrapper.');
