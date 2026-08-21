"""
探索ループの雛形 — Claude Code はこれを拡張する
=================================================
使い方: python3 loop_template.py
やっていること: 全通貨ペア x 全ロジック x パラメータ格子 を回し、
validate_survivor() を通ったものだけ results/ に保存する。

★ Claude Code への申し送り ★
- 新しい手法を試すなら core.py の signal() に型を足し、LOGICS に名前を追加。
- パラメータを広げるのは自由。ただし広げるほど「まぐれ生存者」が増える。
- 生存者が出ても喜ぶな。次を必ずやれ:
    (1) 別のデータソース(別ブローカー/別期間)で再検証。今のデータは
        2012-2022頃。直近3年(2023-2025)で崩れないか別データで確認。
    (2) スプレッドを実際のHFM口座値に上げて再検証(コスト過小評価は禁物)。
    (3) それでも生き残ったら、初めてデモ口座で3ヶ月フォワード。
- 4,488通り検証しても全滅だったのが出発点。安易な生存者ほど疑え。
"""
import core, itertools, json, os, datetime

RESULTS = os.path.join(os.path.dirname(__file__), '..', 'results')

# パラメータ格子(必要に応じて広げてよい。ただし上の警告を読め)
GRID = dict(
    fast=[10,20,30],
    slow=[50,100,200],
    rsi_p=[14],
    sl=[20,40],
    tp=[40,80,120],
    bb_p=[20],
)

def run():
    os.makedirs(RESULTS, exist_ok=True)
    survivors=[]; scanned=0
    for pair in core.PIP_MAP.keys() | {'EURUSD','GBPUSD','AUDUSD','USDCHF','USDCAD','EURGBP'}:
        # 上の集合演算はやや雑。明示リストの方が安全:
        pass
    pairs = ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCHF',
             'USDCAD','EURJPY','GBPJPY','EURGBP','XAUUSD']
    for pair in pairs:
        for logic in core.LOGICS:
            for fast,slow,rsi_p,sl,tp,bb_p in itertools.product(
                GRID['fast'],GRID['slow'],GRID['rsi_p'],GRID['sl'],GRID['tp'],GRID['bb_p']):
                if fast>=slow: continue
                prm=(fast,slow,rsi_p,sl,tp,bb_p); scanned+=1
                passed, det = core.validate_survivor(logic, prm, pair)
                if passed:
                    survivors.append(dict(pair=pair, logic=logic, params=list(prm),
                                          out_pf=det['out_sample']['pf'],
                                          out_exp=det['out_sample']['exp'],
                                          out_n=det['out_sample']['n']))
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(RESULTS, f'survivors_{stamp}.json')
    json.dump(dict(scanned=scanned, survivors=survivors), open(out_path,'w'),
              ensure_ascii=False, indent=2)
    print(f"スキャン {scanned} 通り / 生存 {len(survivors)} 件")
    print(f"結果: {out_path}")
    if survivors:
        print("\n!!! 生存者が出た。喜ぶ前に loop_template.py 冒頭の申し送りを読み、")
        print("    別データ・実スプレッド・デモフォワードで必ず裏を取れ。")
    else:
        print("生存ゼロ。この型の階層にはエッジ無し。次の階層(複数時間足/複合条件)へ。")

if __name__ == '__main__':
    run()
