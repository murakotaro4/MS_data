// 開発用。環境に導入済みのPlaywrightとChromiumを使用し、送信せずレンダーする。
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  const directory = path.resolve(process.argv[2]);
  const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] });
  const results = [];
  try {
    for (const name of fs.readdirSync(directory).filter(name => name.endsWith('.html')).sort()) {
      const original = fs.readFileSync(path.join(directory, name), 'utf8');
      for (const [width, mode] of [[390, 'normal'], [900, 'normal'], [390, 'inline-only']]) {
        const page = await browser.newPage({ viewport: { width, height: 1000 }, deviceScaleFactor: 1 });
        const html = mode === 'normal' ? original : original.replace(/<style>[\s\S]*?<\/style>/g, '');
        await page.setContent(html);
        const metrics = await page.evaluate(() => ({
          viewport: window.innerWidth,
          documentWidth: document.documentElement.scrollWidth,
          height: document.documentElement.scrollHeight,
          textSize: getComputedStyle(document.querySelector('.note') || document.body).fontSize,
          title: document.querySelector('h1').textContent,
          action: document.querySelector('.action').textContent,
          externalResources: document.querySelectorAll('script,img,link').length,
        }));
        const stem = name.slice(0, -5);
        const filename = `${stem}${mode === 'normal' ? '' : '-inline-only'}-${width}.png`;
        await page.screenshot({ path: path.join(directory, filename), fullPage: true });
        results.push({ name, mode, bytes: Buffer.byteLength(html), ...metrics });
        if (Buffer.byteLength(html) > 80 * 1024 || metrics.documentWidth > width || metrics.externalResources || parseFloat(metrics.textSize) < 14) {
          throw new Error(`表示検証に失敗: ${name} / ${width} / ${mode}: ${JSON.stringify(metrics)}`);
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(directory, 'render-checks.json'), JSON.stringify(results, null, 2) + '\n');
  }
  console.log(`レンダー検証成功: ${results.length}件（HTML 80KiB以内、横スクロールなし、補助文字14px以上、外部資源なし）`);
}

main().catch(error => { console.error(error); process.exitCode = 1; });
