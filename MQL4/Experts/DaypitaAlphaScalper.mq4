//+------------------------------------------------------------------+
//|                                          DaypitaAlphaScalper.mq4 |
//|  デイピタアルファ(サイン系インジケーター)の矢印シグナルを        |
//|  iCustom 経由で読み取り、スキャルピング向けの資金管理・決済管理  |
//|  を行うラッパーEA。                                              |
//|                                                                  |
//|  使い方:                                                         |
//|   1. デイピタアルファ本体(ex4/mq4)を MQL4/Indicators へ配置      |
//|   2. チャートに表示し「データウィンドウ」で買い矢印/売り矢印の   |
//|      バッファ番号を確認 → InpBuyBuffer / InpSellBuffer に設定    |
//|   3. インジケーター側に入力パラメータがある場合は、下の          |
//|      GetSignal() 内の iCustom 呼び出しに追記する(コメント参照)   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "デイピタアルファ サイン追従スキャルピングEA"

//--- シグナル取得
input string InpIndicatorName   = "DaypitaAlpha"; // インジケーター名(Indicators内のファイル名、拡張子なし)
input int    InpBuyBuffer       = 0;     // 買い矢印のバッファ番号(データウィンドウで確認)
input int    InpSellBuffer      = 1;     // 売り矢印のバッファ番号
input int    InpSignalShift     = 1;     // シグナル判定バー(1=確定足。リペイント対策のため0は非推奨)

//--- ロット・リスク
input double InpLots            = 0.10;  // 固定ロット(リスク%=0のとき使用)
input double InpRiskPercent     = 1.0;   // 1トレードのリスク(残高%)。0で固定ロット

//--- 決済
input int    InpStopLossPips    = 8;     // 損切り幅(pips)
input int    InpTakeProfitPips  = 6;     // 利確幅(pips)
input bool   InpUseBreakEven    = true;  // 建値ストップ移動を使う
input int    InpBreakEvenPips   = 3;     // 建値移動の発動幅(pips)
input bool   InpUseTrailing     = true;  // トレーリングストップを使う
input int    InpTrailStartPips  = 4;     // トレール開始幅(pips)
input int    InpTrailStepPips   = 2;     // トレール幅(pips)
input int    InpMaxHoldMinutes  = 90;    // 最大保有時間(分)。0で無効
input bool   InpCloseOnOpposite = true;  // 逆シグナル出現で決済する

//--- フィルター
input double InpMaxSpreadPips   = 1.5;   // 許容スプレッド(pips)。超過中はエントリーしない
input int    InpStartHour       = 9;     // 取引開始時刻(サーバー時間)
input int    InpEndHour         = 23;    // 取引終了時刻(サーバー時間)
input int    InpFridayEndHour   = 21;    // 金曜はこの時刻以降エントリー禁止+全決済
input int    InpMaxPositions    = 1;     // 同時保有ポジション数の上限

//--- 執行
input bool   InpEcnMode         = true;  // ECN/ゼロ口座方式(成行約定後にSL/TPを設定)
input int    InpSlippagePoints  = 10;    // 許容スリッページ(points)
input int    InpMagic           = 260716; // マジックナンバー

datetime g_lastEntryBar = 0; // 同一バーでの重複エントリー防止

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpBuyBuffer == InpSellBuffer)
   {
      Alert("買い/売りのバッファ番号が同一です。設定を確認してください。");
      return(INIT_PARAMETERS_INCORRECT);
   }
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnTick()
{
   ManagePositions();          // 決済管理は毎ティック

   if(!IsNewBar())             // エントリー判定は新規バーの頭で1回だけ
      return;

   if(IsFridayCutoff())
   {
      CloseAllPositions("Friday cutoff");
      return;
   }

   if(!IsTradingTime())
      return;

   int signal = GetSignal(InpSignalShift);
   if(signal == 0)
      return;

   if(Time[0] == g_lastEntryBar)
      return;

   if(CountOpenPositions() >= InpMaxPositions)
      return;

   if(CurrentSpreadPips() > InpMaxSpreadPips)
      return;

   if(OpenTrade(signal))
      g_lastEntryBar = Time[0];
}

//+------------------------------------------------------------------+
//| サインツールから矢印シグナルを取得  1=買い -1=売り 0=なし        |
//+------------------------------------------------------------------+
int GetSignal(int shift)
{
   // ※デイピタアルファに入力パラメータがある場合は、インジケーター名と
   //   バッファ番号の間に「表示中と同じ値・同じ順序」で追記すること。
   //   例: iCustom(NULL, 0, InpIndicatorName, 期間, 感度, InpBuyBuffer, shift)
   double up = iCustom(NULL, 0, InpIndicatorName, InpBuyBuffer,  shift);
   double dn = iCustom(NULL, 0, InpIndicatorName, InpSellBuffer, shift);

   bool hasUp = (up != EMPTY_VALUE && up != 0.0);
   bool hasDn = (dn != EMPTY_VALUE && dn != 0.0);

   if(hasUp && !hasDn) return(1);
   if(hasDn && !hasUp) return(-1);
   return(0);
}

//+------------------------------------------------------------------+
bool OpenTrade(int dir)
{
   RefreshRates();
   double pip  = PipSize();
   double lots = CalcLots(InpStopLossPips);
   if(lots <= 0)
      return(false);

   int    type  = (dir > 0) ? OP_BUY : OP_SELL;
   double price = (dir > 0) ? Ask : Bid;
   double sl    = (dir > 0) ? price - InpStopLossPips  * pip
                            : price + InpStopLossPips  * pip;
   double tp    = (dir > 0) ? price + InpTakeProfitPips * pip
                            : price - InpTakeProfitPips * pip;
   sl = NormalizeDouble(sl, Digits);
   tp = NormalizeDouble(tp, Digits);

   // ECN/ゼロ口座はSL/TP同時指定を拒否されることがあるため、後から設定する
   double sendSL = InpEcnMode ? 0 : sl;
   double sendTP = InpEcnMode ? 0 : tp;

   int ticket = OrderSend(Symbol(), type, lots, price, InpSlippagePoints,
                          sendSL, sendTP, "DaypitaAlphaScalper", InpMagic, 0,
                          (dir > 0) ? clrDodgerBlue : clrTomato);
   if(ticket < 0)
   {
      Print("OrderSend失敗 err=", GetLastError());
      return(false);
   }

   if(InpEcnMode && OrderSelect(ticket, SELECT_BY_TICKET))
   {
      // 実際の約定価格を基準にSL/TPを引き直す
      double open = OrderOpenPrice();
      sl = (dir > 0) ? open - InpStopLossPips  * pip : open + InpStopLossPips  * pip;
      tp = (dir > 0) ? open + InpTakeProfitPips * pip : open - InpTakeProfitPips * pip;
      if(!OrderModify(ticket, open, NormalizeDouble(sl, Digits),
                      NormalizeDouble(tp, Digits), 0))
         Print("SL/TP設定失敗 err=", GetLastError());
   }
   return(true);
}

//+------------------------------------------------------------------+
//| 建値移動・トレール・時間切れ・逆シグナルの決済管理               |
//+------------------------------------------------------------------+
void ManagePositions()
{
   RefreshRates();
   double pip = PipSize();
   int oppositeOf = 0;
   if(InpCloseOnOpposite)
      oppositeOf = GetSignal(InpSignalShift);

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != InpMagic) continue;
      if(OrderType() != OP_BUY && OrderType() != OP_SELL) continue;

      bool  isBuy = (OrderType() == OP_BUY);
      double open = OrderOpenPrice();
      double cur  = isBuy ? Bid : Ask;
      double gainPips = (isBuy ? cur - open : open - cur) / pip;

      // 逆シグナル決済
      if(InpCloseOnOpposite &&
         ((isBuy && oppositeOf == -1) || (!isBuy && oppositeOf == 1)))
      {
         ClosePosition(OrderTicket(), "opposite signal");
         continue;
      }

      // 最大保有時間
      if(InpMaxHoldMinutes > 0 &&
         TimeCurrent() - OrderOpenTime() >= InpMaxHoldMinutes * 60)
      {
         ClosePosition(OrderTicket(), "time exit");
         continue;
      }

      double newSL = 0;
      bool   modify = false;

      // 建値ストップ
      if(InpUseBreakEven && gainPips >= InpBreakEvenPips)
      {
         if(isBuy  && (OrderStopLoss() == 0 || OrderStopLoss() < open))
         { newSL = open; modify = true; }
         if(!isBuy && (OrderStopLoss() == 0 || OrderStopLoss() > open))
         { newSL = open; modify = true; }
      }

      // トレーリングストップ(建値移動より優先度高=より有利なSLのみ採用)
      if(InpUseTrailing && gainPips >= InpTrailStartPips)
      {
         double trailSL = isBuy ? cur - InpTrailStepPips * pip
                                : cur + InpTrailStepPips * pip;
         if(isBuy  && trailSL > MathMax(OrderStopLoss(), newSL) + Point)
         { newSL = trailSL; modify = true; }
         if(!isBuy && (OrderStopLoss() == 0 ||
                       trailSL < OrderStopLoss() - Point) &&
                      (newSL == 0 || trailSL < newSL))
         { newSL = trailSL; modify = true; }
      }

      if(modify)
      {
         if(!OrderModify(OrderTicket(), open, NormalizeDouble(newSL, Digits),
                         OrderTakeProfit(), 0))
            Print("OrderModify失敗 err=", GetLastError());
      }
   }
}

//+------------------------------------------------------------------+
void ClosePosition(int ticket, string reason)
{
   if(!OrderSelect(ticket, SELECT_BY_TICKET)) return;
   RefreshRates();
   double price = (OrderType() == OP_BUY) ? Bid : Ask;
   if(!OrderClose(ticket, OrderLots(), price, InpSlippagePoints, clrGray))
      Print("OrderClose失敗(", reason, ") err=", GetLastError());
}

//+------------------------------------------------------------------+
void CloseAllPositions(string reason)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != InpMagic) continue;
      if(OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
      ClosePosition(OrderTicket(), reason);
   }
}

//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderSymbol() != Symbol() || OrderMagicNumber() != InpMagic) continue;
      if(OrderType() == OP_BUY || OrderType() == OP_SELL) count++;
   }
   return(count);
}

//+------------------------------------------------------------------+
//| リスク%からロットを計算(0なら固定ロット)                         |
//+------------------------------------------------------------------+
double CalcLots(double slPips)
{
   if(InpRiskPercent <= 0 || slPips <= 0)
      return(NormalizeLots(InpLots));

   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   if(tickValue <= 0 || tickSize <= 0)
      return(NormalizeLots(InpLots));

   double pipValuePerLot = tickValue * (PipSize() / tickSize);
   double riskMoney = AccountBalance() * InpRiskPercent / 100.0;
   return(NormalizeLots(riskMoney / (slPips * pipValuePerLot)));
}

//+------------------------------------------------------------------+
double NormalizeLots(double lots)
{
   double minLot = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLot = MarketInfo(Symbol(), MODE_MAXLOT);
   double step   = MarketInfo(Symbol(), MODE_LOTSTEP);
   if(step > 0)
      lots = MathFloor(lots / step) * step;
   if(lots < minLot) return(0); // 最小ロット未満は発注しない(過剰リスク防止)
   if(lots > maxLot) lots = maxLot;
   return(NormalizeDouble(lots, 2));
}

//+------------------------------------------------------------------+
//| 3桁/5桁ブローカー対応の1pipサイズ                                |
//+------------------------------------------------------------------+
double PipSize()
{
   return((Digits == 3 || Digits == 5) ? Point * 10 : Point);
}

//+------------------------------------------------------------------+
double CurrentSpreadPips()
{
   return((Ask - Bid) / PipSize());
}

//+------------------------------------------------------------------+
bool IsNewBar()
{
   static datetime lastBar = 0;
   if(Time[0] == lastBar) return(false);
   lastBar = Time[0];
   return(true);
}

//+------------------------------------------------------------------+
bool IsTradingTime()
{
   int h = Hour();
   if(InpStartHour <= InpEndHour)
      return(h >= InpStartHour && h < InpEndHour);
   return(h >= InpStartHour || h < InpEndHour); // 日をまたぐ設定にも対応
}

//+------------------------------------------------------------------+
bool IsFridayCutoff()
{
   return(DayOfWeek() == 5 && Hour() >= InpFridayEndHour);
}
//+------------------------------------------------------------------+
