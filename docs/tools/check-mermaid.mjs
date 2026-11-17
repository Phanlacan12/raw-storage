import { JSDOM } from 'jsdom';
import fs from 'fs';
import path from 'path';

const dom = new JSDOM('<!doctype html><html><body></body></html>', { pretendToBeVisual: true });
global.window = dom.window;
global.document = dom.window.document;
Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });
global.DOMPurify = undefined;
global.Element = dom.window.Element;
global.SVGElement = dom.window.SVGElement;
global.HTMLElement = dom.window.HTMLElement;
global.getComputedStyle = dom.window.getComputedStyle;

const mermaid = (await import('mermaid')).default;
mermaid.initialize({ startOnLoad: false, securityLevel: 'loose' });

const dir = process.argv[2];
const files = fs.readdirSync(dir).filter(f => f.endsWith('.md'));
let fail = 0;
for (const f of files) {
  const src = fs.readFileSync(path.join(dir, f), 'utf8');
  const lines = src.split('\n');
  let i = 0, idx = 0;
  while (i < lines.length) {
    if (lines[i].trim() === '```mermaid') {
      const start = i + 1;
      let j = start;
      while (j < lines.length && lines[j].trim() !== '```') j++;
      const code = lines.slice(start, j).join('\n');
      idx++;
      try {
        await mermaid.parse(code);
        console.log(`OK    ${f} #${idx} (line ${start + 1}) ${code.split('\n')[0].trim()}`);
      } catch (e) {
        fail++;
        console.log(`FAIL  ${f} #${idx} (line ${start + 1}) ${code.split('\n')[0].trim()}`);
        console.log('      ' + String(e.message || e).split('\n').slice(0, 6).join('\n      '));
      }
      i = j + 1;
    } else i++;
  }
}
console.log(`\n${fail} diagram lỗi`);
