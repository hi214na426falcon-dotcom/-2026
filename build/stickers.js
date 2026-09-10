'use strict';
// 32個のスタンプ定義（案A：カワウソ16＋柴犬16）
// n: 通し番号(申請順), file: 出力名, char, caption(配列で改行), face, arms, prop, propBehind

const OTTER = [
  { caption: ['これはこれ、', 'それはそれ'], face: 'calm',      arms: 'outPalms' },
  { caption: 'で、要点は？',                  face: 'bored',     arms: 'pointFwd' },
  { caption: 'それって私の仕事？',            face: 'skeptical', arms: 'pointSelf' },
  { caption: '知らんけど',                    face: 'away',      arms: 'shrug' },
  { caption: 'いま忙しいんで',                face: 'away',      arms: 'busy', prop: 'phone', propBehind: false },
  { caption: '反省してまーす',                face: 'smug',      arms: 'apology' },
  { caption: ['拍手喝采', '（無感情）'],       face: 'deadpan',   arms: 'clap' },
  { caption: '話長いね',                      face: 'bored',     arms: 'cheek' },
  { caption: 'お金くれたらやる',              face: 'greedy',    arms: 'greedy' },
  { caption: '全部忘れた',                    face: 'clueless',  arms: 'onHead' },
  { caption: '草生える',                      face: 'laugh',     arms: 'laughHold' },
  { caption: ['それ、言わなくて', 'よくない？'], face: 'awkward',   arms: 'coverMouth' },
  { caption: 'もう帰りたーい',                face: 'whiny',     arms: 'limp' },
  { caption: '奢りですよね？',                face: 'hopeful',   arms: 'clasp' },
  { caption: '解散！',                        face: 'cheer',     arms: 'upCheer' },
  { caption: ['ありがと', '（棒読み）'],       face: 'monotone',  arms: 'wave' },
];

const SHIBA = [
  { caption: ['これはこれ、', 'それはそれ'], face: 'calm',       arms: 'outPalms' },
  { caption: '拒否権を行使',                  face: 'refuse',     arms: 'crossX' },
  { caption: '聞こえましぇーん',              face: 'silly',      arms: 'coverEars' },
  { caption: ['それ、あなたの', '感想ですよね'], face: 'smirk',     arms: 'pointFwd' },
  { caption: '解釈違いです',                  face: 'distressed', arms: 'objection' },
  { caption: ['後でやる', '（やらない）'],     face: 'relaxed',    arms: 'lazy' },
  { caption: 'え、私のせい？',                face: 'shocked',    arms: 'pointSelf' },
  { caption: '草',                            face: 'amused',     arms: 'laughHold' },
  { caption: '明日から本気出す',              face: 'smirk',      arms: 'lazy' },
  { caption: 'お金で解決しよ？',              face: 'wink',       arms: 'coin', prop: 'coin', propBehind: true },
  { caption: ['はいはい、', 'すごいすごい'],   face: 'bored',      arms: 'clap' },
  { caption: '既読だけつけた',                face: 'away',       arms: 'phone2', prop: 'phone2', propBehind: true },
  { caption: '都合のいい耳',                  face: 'smirk',      arms: 'cupEar' },
  { caption: 'お疲れ、自分',                  face: 'content',    arms: 'patHead' },
  { caption: ['無理です', '（真顔）'],         face: 'deadpan',    arms: 'palmStop' },
  { caption: ['おっけー', '（気が向いたら）'], face: 'smirk',      arms: 'okhand' },
];

function pad(n) { return String(n).padStart(2, '0'); }

const list = [];
OTTER.forEach((s, i) => list.push(Object.assign({ char: 'otter', n: i + 1, file: `otter-${pad(i + 1)}` }, s)));
SHIBA.forEach((s, i) => list.push(Object.assign({ char: 'shiba', n: i + 1, file: `shiba-${pad(i + 1)}` }, s)));

// メイン画像＆タブ画像に使うポーズ（テキストなし）
const MAIN = { char: 'otter', face: 'hopeful', arms: 'rest' };    // 240x240
const TAB  = { char: 'shiba', face: 'content', arms: 'rest' };    // 96x74（顔アップ）

module.exports = { list, OTTER, SHIBA, MAIN, TAB };
