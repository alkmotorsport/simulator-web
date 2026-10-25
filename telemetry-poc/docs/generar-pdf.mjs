// Genera docs/manual-usuario.pdf y docs/manual-administrador.pdf desde los .md
// (A4, con logo y numero de pagina). Necesita Google Chrome y, una vez:
//   cd telemetry-poc/docs && npm i --no-save puppeteer-core@23 marked@12
// Uso:  node docs/generar-pdf.mjs docs web/logo.jpg     (desde telemetry-poc)
// En Linux/Windows, pon la ruta de Chrome en CHROME=...

import puppeteer from 'puppeteer-core';
import { marked } from 'marked';
import fs from 'fs';
import path from 'path';
const [DOCS, LOGO] = process.argv.slice(2);
const logo = 'data:image/jpeg;base64,' + fs.readFileSync(LOGO).toString('base64');
const CSS = `
  @page { size: A4; margin: 18mm 16mm 20mm; }
  body { font: 10.5pt/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #1a2430; }
  .portada { display: flex; align-items: center; gap: 14px; border-bottom: 3px solid #d25028; padding-bottom: 10px; margin-bottom: 14px; }
  .portada img { width: 56px; height: 56px; border-radius: 10px; }
  .portada small { color: #5a6676; }
  h1 { font-size: 19pt; color: #14283c; margin: 0; }
  h2 { font-size: 14pt; color: #14283c; border-bottom: 1px solid #e1e5ea; padding-bottom: 3px; margin: 20px 0 8px; break-after: avoid; }
  h3 { font-size: 11.5pt; color: #14283c; margin: 14px 0 6px; break-after: avoid; }
  p, li { orphans: 3; widows: 3; }
  a { color: #466e96; text-decoration: none; }
  code { font: 9pt ui-monospace, Menlo, Consolas, monospace; background: #f3f5f8; border: 1px solid #e1e5ea; border-radius: 4px; padding: 0 3px; }
  pre { background: #f3f5f8; border: 1px solid #e1e5ea; border-radius: 6px; padding: 8px 10px; white-space: pre-wrap; break-inside: avoid; }
  pre code { border: 0; padding: 0; background: none; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9.5pt; break-inside: auto; }
  th, td { border: 1px solid #e1e5ea; padding: 5px 7px; vertical-align: top; text-align: left; }
  th { background: #14283c; color: #fff; }
  tr { break-inside: avoid; }
  hr { border: 0; border-top: 1px solid #e1e5ea; margin: 14px 0; }
`;
const browser = await puppeteer.launch({ executablePath: process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
for (const nombre of ['manual-usuario', 'manual-administrador']) {
  const md = fs.readFileSync(path.join(DOCS, nombre + '.md'), 'utf8');
  const [primera, ...resto] = md.split('\n');
  const titulo = primera.replace(/^#\s*/, '');
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>${titulo}</title><style>${CSS}</style></head><body>
    <div class="portada"><img src="${logo}" alt=""><div><h1>${titulo}</h1><small>Versión del ${new Date().toLocaleDateString('es-ES')}</small></div></div>
    ${marked.parse(resto.join('\n'))}</body></html>`;
  const page = await browser.newPage();
  await page.setContent(html, { waitUntil: 'load' });
  await page.pdf({
    path: path.join(DOCS, nombre + '.pdf'), format: 'A4', printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: `<div style="font-size:8pt;color:#5a6676;width:100%;padding:0 16mm;display:flex;justify-content:space-between"><span>${titulo}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
    margin: { top: '18mm', bottom: '20mm', left: '16mm', right: '16mm' },
  });
  await page.close();
  console.log(nombre + '.pdf', Math.round(fs.statSync(path.join(DOCS, nombre + '.pdf')).size / 1024) + ' kB');
}
await browser.close();
