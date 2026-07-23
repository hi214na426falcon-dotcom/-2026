import { chromium } from 'playwright';

const BASE = 'http://localhost:5000';
const email = `admin${Date.now()}@yuime.local`;
const password = 'password123';

const log = (...a) => console.log('  ', ...a);
let failures = 0;
function check(cond, msg) {
  if (cond) { console.log('✅', msg); }
  else { console.log('❌', msg); failures++; }
}

// 環境変数 CHROME_PATH があればそれを使用（無ければ Playwright 同梱の Chromium）
const launchOpts = process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
const browser = await chromium.launch(launchOpts);
let page = await browser.newPage();
page.on('console', (m) => { if (m.type() === 'error') log('[console.error]', m.text()); });

try {
  // 1) 管理者作成
  await page.goto(`${BASE}/setup-admin.html`, { waitUntil: 'domcontentloaded' });
  await page.fill('#adminName', 'テスト管理者');
  await page.fill('#adminEmail', email);
  await page.fill('#adminPassword', password);
  page.once('dialog', (d) => d.accept());
  await page.click('#setupForm button[type="submit"]');
  await page.waitForURL('**/index.html', { timeout: 10000 }).catch(() => {});
  check(page.url().includes('index.html') || page.url().endsWith('/'), '管理者作成 → ログイン画面へ遷移');

  // 1.5) いったんログアウト（作成直後は自動ログイン状態のため）
  await page.goto(`${BASE}/dashboard.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('button:has-text("ログアウト")', { timeout: 10000 });
  await page.click('button:has-text("ログアウト")');
  await page.waitForURL('**/index.html', { timeout: 10000 });

  // 2) ログイン
  await page.waitForSelector('#email', { timeout: 10000 });
  await page.fill('#email', email);
  await page.fill('#password', password);
  await page.click('#loginBtn');
  await page.waitForURL('**/dashboard.html', { timeout: 10000 });
  check(page.url().includes('dashboard.html'), 'ログイン成功 → ダッシュボード表示');

  // 3) 会社を作成
  await page.goto(`${BASE}/companies.html`, { waitUntil: 'domcontentloaded' });
  await page.click('button:has-text("+ 新規作成")');
  await page.fill('#companyName', '株式会社テスト建設');
  await page.selectOption('#companyType', 'prime');
  await page.click('#companyForm button[type="submit"]');
  await page.waitForTimeout(1500);
  check((await page.textContent('#companiesList')).includes('株式会社テスト建設'), '会社を登録できた');

  // 4) 現場を作成
  await page.goto(`${BASE}/sites.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await page.click('button:has-text("+ 新規作成")');
  await page.fill('#siteName', '第一現場');
  await page.selectOption('#siteCompany', { index: 0 });
  await page.fill('#siteManager', '現場太郎');
  await page.click('#siteForm button[type="submit"]');
  await page.waitForTimeout(1500);
  check((await page.textContent('#sitesList')).includes('第一現場'), '現場を登録できた');
  check((await page.textContent('#sitesList')).includes('0人 の名簿'), '新規現場の配属人数が0人');

  // 5) 作業員を作成（現場に配属） — 新しいコンテキストで独立接続
  const ctx2 = await browser.newContext();
  const page2 = await ctx2.newPage();
  page2.on('console', (m) => { if (m.type() === 'error') log('[p2 console.error]', m.text()); });
  await page2.goto(`${BASE}/index.html`, { waitUntil: 'domcontentloaded' });
  await page2.waitForSelector('#email', { timeout: 10000 });
  await page2.fill('#email', email);
  await page2.fill('#password', password);
  await page2.click('#loginBtn');
  await page2.waitForURL('**/dashboard.html', { timeout: 10000 });
  const page_old = page;
  page = page2;
  await page.goto(`${BASE}/workers.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => Array.from(document.querySelectorAll('#workerSite option')).some((o) => o.textContent.includes('第一現場')),
    { timeout: 15000 }
  );
  await page.click('button:has-text("+ 新規作成")');
  await page.fill('#workerName', 'グエン・ヴァン・A');
  await page.selectOption('#workerCompany', { index: 0 });
  await page.selectOption('#workerSite', { label: '第一現場' });
  await page.fill('#workerNationality', 'ベトナム');
  await page.fill('#workerVisaType', '技能実習');
  await page.fill('#workerSkill', '鉄筋工');
  await page.click('#workerForm button[type="submit"]');
  // 保存反映を最大10秒ポーリング
  await page.waitForFunction(
    () => document.getElementById('workersList').textContent.includes('グエン・ヴァン・A'),
    { timeout: 25000 }
  ).catch(() => {});
  const workersText = await page.textContent('#workersList');
  check(workersText.includes('グエン・ヴァン・A'), '作業員を登録できた');
  check(workersText.includes('第一現場'), '作業員一覧に配属現場が表示される');

  // 6) 現場名簿で確認
  await page.goto(`${BASE}/sites.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => document.getElementById('sitesList').textContent.includes('1人 の名簿'),
    { timeout: 25000 }
  ).catch(() => {});
  check((await page.textContent('#sitesList')).includes('1人 の名簿'), '現場の配属人数が1人に更新された');
  await page.click('button:has-text("1人 の名簿")');
  await page.waitForTimeout(500);
  const roster = await page.textContent('#rosterList');
  check(roster.includes('グエン・ヴァン・A'), '現場名簿に配属作業員が表示される');
  check(roster.includes('鉄筋工'), '名簿に職能が表示される');

  // 7) ダッシュボード
  await page.goto(`${BASE}/dashboard.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  check((await page.textContent('#assignedCount')) === '1', 'ダッシュボード：配属済み1名');
  check((await page.textContent('#siteRosterList')).includes('第一現場'), 'ダッシュボード：現場別名簿に第一現場');

  // 8) 現場フィルタ
  await page.goto(`${BASE}/workers.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await page.selectOption('#siteFilter', { label: '第一現場' });
  await page.waitForTimeout(400);
  check((await page.textContent('#workersList')).includes('グエン・ヴァン・A'), '現場フィルタで絞り込める');

} catch (e) {
  console.log('❌ 例外:', e.message);
  failures++;
} finally {
  await browser.close();
}

console.log(failures === 0 ? '\n🎉 全テスト成功' : `\n⚠️ ${failures}件 失敗`);
process.exit(failures === 0 ? 0 : 1);
