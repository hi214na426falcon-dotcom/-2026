//+------------------------------------------------------------------+
//| MultiAssetTrendVT.mq5                                            |
//| Multi-asset (Gold / Crypto / FX) volatility-targeted trend EA     |
//|                                                                  |
//| Logic is identical to research/engine.py (D1 bars, weekdays):     |
//|  1. signal  = mean of sign(Close/Close[L]-1) over L in Lookbacks  |
//|  2. raw     = signal * classBudget / (EWMA vol * sqrt(252))       |
//|  3. scale book to target portfolio vol using rolling covariance  |
//|  4. drawdown brake, per-asset leverage caps, gross leverage cap  |
//|  5. rebalance only when target differs from holding by > buffer  |
//|  6. broker-side hard stop (ATR multiple) + cooldown after a stop |
//| No martingale, no averaging down. Size only grows when the trend |
//| signal strengthens or volatility falls (risk-parity rebalancing).|
//+------------------------------------------------------------------+
#property copyright "MultiAssetTrendVT"
#property version   "1.00"
#property description "Volatility-targeted time-series-momentum ensemble for Gold / Crypto / FX (D1)."

#include <Trade/Trade.mqh>

//--- universe
input string InpSymbols        = "XAUUSD,BTCUSD,EURUSD,GBPUSD,AUDUSD,USDJPY,USDCAD,USDCHF"; // Symbols (comma separated)
input string InpClasses        = "gold,crypto,fx,fx,fx,fx,fx,fx";   // Class per symbol: gold / crypto / fx
input string InpSymbolSuffix   = "";                                // Broker suffix (e.g. ".m", "micro")
input string InpLongOnly       = "XAUUSD,BTCUSD";                   // Long-only symbols (walk-forward choice)
//--- signal
input string InpLookbacks      = "10,20,40,80";                     // TSMOM lookbacks (D1 weekday bars)
input int    InpVolSpan        = 60;                                // EWMA span for volatility
input int    InpCovWindow      = 120;                               // Covariance window (bars)
//--- risk
input double InpPortVol        = 0.15;   // Target annual portfolio volatility (0.15 = 15%)
input double InpBudgetGold     = 1.0;    // Risk budget: gold
input double InpBudgetCrypto   = 1.0;    // Risk budget: crypto
input double InpBudgetFX       = 0.0;    // Risk budget: FX (0 = off; see README)
input double InpLevCapGold     = 2.0;    // Max notional/equity per gold symbol
input double InpLevCapCrypto   = 0.6;    // Max notional/equity per crypto symbol
input double InpLevCapFX       = 4.0;    // Max notional/equity per FX symbol
input double InpMaxGross       = 6.0;    // Max total notional/equity
input double InpCapitalPct     = 100.0;  // % of equity used as capital base
input double InpDD1            = 0.15;   // Drawdown level 1
input double InpDD1Mult        = 0.50;   // Risk multiplier at DD level 1
input double InpDD2            = 0.25;   // Drawdown level 2
input double InpDD2Mult        = 0.25;   // Risk multiplier at DD level 2
input double InpHardStopATR    = 6.0;    // Broker-side stop distance in ATR (0 = none)
input int    InpATRPeriod      = 20;     // ATR period (D1)
input int    InpCooldownDays   = 10;     // Weekdays flat after a stop-out
input bool   InpCarryFilterFX  = false;  // FX: trade only in positive-swap direction (unvalidated)
//--- execution
input double InpRebalBuffer    = 0.25;   // Rebalance only if |target-current| > buffer*|target|
input int    InpTradeHour      = 1;      // Earliest server hour to trade each day
input double InpMaxSpreadPct   = 0.20;   // Skip if spread > this % of price
input double InpMinFreeMarginPct = 40.0; // Keep free margin >= this % of equity
input int    InpSlippagePoints = 50;     // Max deviation (points)
input long   InpMagic          = 26042026;
input bool   InpResetPeak      = false;  // Reset stored equity peak on start
input bool   InpVerbose        = true;

#define CLS_GOLD   0
#define CLS_CRYPTO 1
#define CLS_FX     2
#define NCAL       600     // weekday calendar length used for calculations
#define MEDWIN     250     // window for volatility floor median

CTrade   g_trade;
string   g_sym[];
int      g_cls[];
bool     g_longOnly[];
int      g_lb[];
int      g_n = 0;
int      g_maxLB = 0;
datetime g_doneDay[];      // per-symbol: day already processed
datetime g_coolUntil[];
string   g_gv;             // global-variable prefix

//+------------------------------------------------------------------+
string Trim(string s) { StringTrimLeft(s); StringTrimRight(s); return s; }

int SplitList(const string src, string &out[])
{
   string tmp[];
   int k = StringSplit(src, ',', tmp);
   ArrayResize(out, 0);
   for(int i = 0; i < k; i++)
   {
      string t = Trim(tmp[i]);
      if(t == "") continue;
      int m = ArraySize(out);
      ArrayResize(out, m + 1);
      out[m] = t;
   }
   return ArraySize(out);
}

datetime DayStart(datetime t) { return t - (t % 86400); }

bool IsWeekday(datetime t)
{
   MqlDateTime s; TimeToStruct(t, s);
   return (s.day_of_week >= 1 && s.day_of_week <= 5);
}

//+------------------------------------------------------------------+
int OnInit()
{
   string syms[], cls[], lo[], lbs[];
   int ns = SplitList(InpSymbols, syms);
   int nc = SplitList(InpClasses, cls);
   if(ns == 0 || ns != nc) { Print("Symbols / classes count mismatch"); return INIT_PARAMETERS_INCORRECT; }
   SplitList(InpLongOnly, lo);
   int nl = SplitList(InpLookbacks, lbs);
   if(nl == 0) { Print("No lookbacks"); return INIT_PARAMETERS_INCORRECT; }

   ArrayResize(g_lb, nl);
   g_maxLB = 0;
   for(int i = 0; i < nl; i++) { g_lb[i] = (int)StringToInteger(lbs[i]); if(g_lb[i] < 1) return INIT_PARAMETERS_INCORRECT; if(g_lb[i] > g_maxLB) g_maxLB = g_lb[i]; }
   if(g_maxLB + 2 >= NCAL || InpCovWindow + 2 >= NCAL || InpCovWindow < 20) { Print("Lookback too long"); return INIT_PARAMETERS_INCORRECT; }

   g_n = ns;
   ArrayResize(g_sym, g_n); ArrayResize(g_cls, g_n); ArrayResize(g_longOnly, g_n);
   ArrayResize(g_doneDay, g_n); ArrayResize(g_coolUntil, g_n);
   g_gv = "MATVT_" + IntegerToString(InpMagic) + "_";
   for(int i = 0; i < g_n; i++)
   {
      g_sym[i] = syms[i] + InpSymbolSuffix;
      string c = cls[i]; StringToLower(c);
      g_cls[i] = (c == "gold") ? CLS_GOLD : (c == "crypto" ? CLS_CRYPTO : CLS_FX);
      g_longOnly[i] = false;
      for(int j = 0; j < ArraySize(lo); j++) if(lo[j] == syms[i]) g_longOnly[i] = true;
      if(!SymbolSelect(g_sym[i], true)) PrintFormat("WARNING: symbol %s not available", g_sym[i]);
      g_doneDay[i] = 0;
      string k = g_gv + "cool_" + g_sym[i];
      g_coolUntil[i] = GlobalVariableCheck(k) ? (datetime)GlobalVariableGet(k) : 0;
   }
   if(InpResetPeak || !GlobalVariableCheck(g_gv + "peak"))
      GlobalVariableSet(g_gv + "peak", AccountInfoDouble(ACCOUNT_EQUITY));

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   EventSetTimer(60);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); Comment(""); }

void OnTick()  { Process(); }
void OnTimer() { Process(); }

//+------------------------------------------------------------------+
//| Weekday calendar: last NCAL completed weekdays, oldest first     |
//+------------------------------------------------------------------+
void BuildCalendar(datetime &cal[])
{
   ArrayResize(cal, NCAL);
   datetime d = DayStart(TimeCurrent()) - 86400;     // last completed day
   int k = NCAL - 1;
   while(k >= 0)
   {
      if(IsWeekday(d)) { cal[k] = d; k--; }
      d -= 86400;
   }
}

// Aligned closes on calendar (forward-filled). Returns false if insufficient history.
bool AlignedCloses(const string sym, const datetime &cal[], double &out[])
{
   MqlRates r[];
   int need = (int)(NCAL * 1.5) + 20;               // crypto has weekend bars
   int got = CopyRates(sym, PERIOD_D1, 1, need, r);  // from shift 1 = completed bars
   if(got <= 0) return false;
   ArrayResize(out, NCAL);
   int j = 0;
   double last = EMPTY_VALUE;
   for(int k = 0; k < NCAL; k++)
   {
      while(j < got && DayStart(r[j].time) <= cal[k])
      {
         if(IsWeekday(r[j].time)) last = r[j].close;
         j++;
      }
      out[k] = last;
   }
   // need full data over the window actually used
   int span = g_maxLB;
   if(InpCovWindow + 1 > span) span = InpCovWindow + 1;
   if(MEDWIN + 1 > span) span = MEDWIN + 1;
   int first = NCAL - 1 - span;
   for(int k = first; k < NCAL; k++) if(out[k] == EMPTY_VALUE || out[k] <= 0) return false;
   // stale-data guard: last bar must be recent (within 5 calendar days)
   if(DayStart(r[got - 1].time) < cal[NCAL - 1] - 5 * 86400) return false;
   return true;
}

double ATR(const string sym, int period)
{
   MqlRates r[];
   int got = CopyRates(sym, PERIOD_D1, 1, period + 1, r);
   if(got < period + 1) return 0;
   double s = 0;
   for(int i = 1; i < got; i++)
   {
      double tr = MathMax(r[i].high, r[i - 1].close) - MathMin(r[i].low, r[i - 1].close);
      s += tr;
   }
   return s / (got - 1);
}

//+------------------------------------------------------------------+
//| Position helpers                                                  |
//+------------------------------------------------------------------+
double NetLots(const string sym)
{
   double v = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != sym || PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      double vol = PositionGetDouble(POSITION_VOLUME);
      v += (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? vol : -vol;
   }
   return v;
}

// account-currency notional of 1.0 lot
double LotNotional(const string sym)
{
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double px = SymbolInfoDouble(sym, SYMBOL_BID);
   if(ts <= 0 || tv <= 0 || px <= 0) return 0;
   return px / ts * tv;
}

double NormLots(const string sym, double lots)
{
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;
   lots = MathFloor(lots / step + 1e-9) * step;
   if(lots < mn) return 0;
   if(lots > mx) lots = mx;
   return NormalizeDouble(lots, 8);
}

bool CloseAll(const string sym)
{
   bool ok = true;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != sym || PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(!g_trade.PositionClose(t)) ok = false;
   }
   return ok;
}

bool Reduce(const string sym, double lots)
{
   double rem = lots;
   for(int i = PositionsTotal() - 1; i >= 0 && rem > 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != sym || PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      double vol = PositionGetDouble(POSITION_VOLUME);
      if(vol <= rem + 1e-9) { if(!g_trade.PositionClose(t)) return false; rem -= vol; }
      else
      {
         double part = NormLots(sym, rem);
         if(part > 0 && !g_trade.PositionClosePartial(t, part)) return false;
         rem = 0;
      }
   }
   return true;
}

bool Open(const string sym, double lots, bool buy)
{
   if(lots <= 0) return true;
   // margin guard
   double price = buy ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
   double margin = 0;
   if(OrderCalcMargin(buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, lots, price, margin))
   {
      double eq = AccountInfoDouble(ACCOUNT_EQUITY);
      double fm = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      double floorFM = eq * InpMinFreeMarginPct / 100.0;
      if(fm - margin < floorFM)
      {
         double room = fm - floorFM;
         if(room <= 0 || margin <= 0) { PrintFormat("%s: margin guard blocked order", sym); return false; }
         lots = NormLots(sym, lots * room / margin);
         if(lots <= 0) return false;
      }
   }
   double sl = 0;
   if(InpHardStopATR > 0)
   {
      double atr = ATR(sym, InpATRPeriod);
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      if(atr > 0) sl = NormalizeDouble(buy ? price - InpHardStopATR * atr : price + InpHardStopATR * atr, digits);
      if(sl <= 0) sl = 0;
   }
   g_trade.SetTypeFillingBySymbol(sym);
   bool ok = buy ? g_trade.Buy(lots, sym, 0, sl, 0, "MATVT") : g_trade.Sell(lots, sym, 0, sl, 0, "MATVT");
   if(!ok) PrintFormat("%s: order failed %d %s", sym, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
   return ok;
}

//+------------------------------------------------------------------+
//| Main daily routine                                                |
//+------------------------------------------------------------------+
void Process()
{
   datetime now = TimeCurrent();
   double eqNow = AccountInfoDouble(ACCOUNT_EQUITY);
   double peak = GlobalVariableGet(g_gv + "peak");
   if(eqNow > peak) { peak = eqNow; GlobalVariableSet(g_gv + "peak", peak); }

   if(!IsWeekday(now)) return;
   MqlDateTime s; TimeToStruct(now, s);
   if(s.hour < InpTradeHour) return;
   datetime today = DayStart(now);
   bool pending = false;
   for(int i = 0; i < g_n; i++) if(g_doneDay[i] != today) pending = true;
   if(!pending) return;

   //--- 1) data
   datetime cal[];
   BuildCalendar(cal);
   double C[];                      // flattened [i*NCAL + k]
   ArrayResize(C, g_n * NCAL);
   bool live[];
   ArrayResize(live, g_n);
   for(int i = 0; i < g_n; i++)
   {
      double tmp[];
      live[i] = AlignedCloses(g_sym[i], cal, tmp);
      for(int k = 0; k < NCAL; k++) C[i * NCAL + k] = live[i] ? tmp[k] : 0;
   }

   //--- 2) EWMA vol with floor, and signal
   double dvol[], sig[];
   ArrayResize(dvol, g_n); ArrayResize(sig, g_n);
   double a = 2.0 / (InpVolSpan + 1.0);
   for(int i = 0; i < g_n; i++)
   {
      dvol[i] = 0; sig[i] = 0;
      if(!live[i]) continue;
      double hist[]; ArrayResize(hist, NCAL);
      double v = -1;
      int firstValid = 0;
      while(firstValid < NCAL && C[i * NCAL + firstValid] == EMPTY_VALUE) firstValid++;
      for(int k = 0; k < NCAL; k++) hist[k] = 0;
      for(int k = firstValid + 1; k < NCAL; k++)
      {
         double r = C[i * NCAL + k] / C[i * NCAL + k - 1] - 1.0;
         v = (v < 0) ? r * r : (1 - a) * v + a * r * r;
         hist[k] = MathSqrt(v);
      }
      double med[]; ArrayResize(med, MEDWIN);
      for(int k = 0; k < MEDWIN; k++) med[k] = hist[NCAL - MEDWIN + k];
      ArraySort(med);
      double median = (MEDWIN % 2 == 1) ? med[MEDWIN / 2] : 0.5 * (med[MEDWIN / 2 - 1] + med[MEDWIN / 2]);
      dvol[i] = MathMax(hist[NCAL - 1], 0.5 * median);
      if(dvol[i] <= 0) { live[i] = false; continue; }
      double last = C[i * NCAL + NCAL - 1];
      for(int j = 0; j < ArraySize(g_lb); j++)
      {
         double past = C[i * NCAL + NCAL - 1 - g_lb[j]];
         double x = last / past - 1.0;
         sig[i] += (x > 0) ? 1.0 : (x < 0 ? -1.0 : 0.0);
      }
      sig[i] /= ArraySize(g_lb);
   }

   //--- 3) budgets
   double clsBudget[3]; clsBudget[0] = InpBudgetGold; clsBudget[1] = InpBudgetCrypto; clsBudget[2] = InpBudgetFX;
   int clsCount[3] = {0, 0, 0};
   for(int i = 0; i < g_n; i++) if(live[i]) clsCount[g_cls[i]]++;
   double bud[]; ArrayResize(bud, g_n);
   double bsum = 0;
   for(int i = 0; i < g_n; i++)
   {
      bud[i] = live[i] ? clsBudget[g_cls[i]] / clsCount[g_cls[i]] : 0;
      bsum += bud[i];
   }
   double raw[]; ArrayResize(raw, g_n);
   for(int i = 0; i < g_n; i++)
   {
      raw[i] = 0;
      if(!live[i] || bsum <= 0) continue;
      raw[i] = sig[i] * (bud[i] / bsum) / (dvol[i] * MathSqrt(252.0));
      if(g_longOnly[i] && raw[i] < 0) raw[i] = 0;
      if(g_coolUntil[i] > now) raw[i] = 0;
      if(InpCarryFilterFX && g_cls[i] == CLS_FX)
      {
         if(raw[i] > 0 && SymbolInfoDouble(g_sym[i], SYMBOL_SWAP_LONG) < 0) raw[i] = 0;
         if(raw[i] < 0 && SymbolInfoDouble(g_sym[i], SYMBOL_SWAP_SHORT) < 0) raw[i] = 0;
      }
   }

   //--- 4) ex-ante portfolio vol (sample covariance of last InpCovWindow+1 returns)
   int m = InpCovWindow + 1;
   double R[]; ArrayResize(R, g_n * m);
   double mu[]; ArrayResize(mu, g_n);
   for(int i = 0; i < g_n; i++)
   {
      mu[i] = 0;
      for(int k = 0; k < m; k++)
      {
         int idx = NCAL - m + k;
         R[i * m + k] = live[i] ? C[i * NCAL + idx] / C[i * NCAL + idx - 1] - 1.0 : 0;
         mu[i] += R[i * m + k];
      }
      mu[i] /= m;
   }
   double pv2 = 0;
   for(int i = 0; i < g_n; i++)
   {
      if(raw[i] == 0) continue;
      for(int j = 0; j < g_n; j++)
      {
         if(raw[j] == 0) continue;
         double c = 0;
         for(int k = 0; k < m; k++) c += (R[i * m + k] - mu[i]) * (R[j * m + k] - mu[j]);
         c = c / (m - 1) * 252.0;
         pv2 += raw[i] * raw[j] * c;
      }
   }
   double pv = MathSqrt(MathMax(pv2, 1e-12));

   //--- 5) targets
   double dd = (peak > 0) ? 1.0 - eqNow / peak : 0;
   double mult = 1.0;
   if(dd >= InpDD1) mult = InpDD1Mult;
   if(dd >= InpDD2) mult = InpDD2Mult;
   double tgt[]; ArrayResize(tgt, g_n);
   double gross = 0;
   for(int i = 0; i < g_n; i++)
   {
      tgt[i] = (pv > 1e-6) ? raw[i] * InpPortVol / pv * mult : 0;
      double cap = (g_cls[i] == CLS_GOLD) ? InpLevCapGold : (g_cls[i] == CLS_CRYPTO ? InpLevCapCrypto : InpLevCapFX);
      tgt[i] = MathMax(-cap, MathMin(cap, tgt[i]));
      gross += MathAbs(tgt[i]);
   }
   if(gross > InpMaxGross) for(int i = 0; i < g_n; i++) tgt[i] *= InpMaxGross / gross;

   //--- 6) execution
   double capital = eqNow * InpCapitalPct / 100.0;
   string report = StringFormat("MATVT  equity=%.2f  peak=%.2f  DD=%.1f%%  riskMult=%.2f  exAnteVol(raw)=%.3f\n",
                                eqNow, peak, dd * 100, mult, pv);
   for(int i = 0; i < g_n; i++)
   {
      string sym = g_sym[i];
      double ln = LotNotional(sym);
      double cur = NetLots(sym);
      double curW = (ln > 0 && capital > 0) ? cur * ln / capital : 0;
      double tgtLots = (ln > 0) ? NormLots(sym, MathAbs(tgt[i]) * capital / ln) : 0;
      double tgtSigned = (tgt[i] >= 0) ? tgtLots : -tgtLots;
      double tgtW = (ln > 0 && capital > 0) ? tgtSigned * ln / capital : 0;
      report += StringFormat("%-10s live=%d sig=%+.2f vol=%.1f%% tgtW=%+.3f curW=%+.3f lots %.2f->%.2f\n",
                             sym, (int)live[i], sig[i], dvol[i] * MathSqrt(252.0) * 100, tgtW, curW, cur, tgtSigned);
      if(g_doneDay[i] == today) continue;
      if(!live[i] && cur == 0) { g_doneDay[i] = today; continue; }
      if(!live[i]) { PrintFormat("%s: no valid data today, holding position", sym); g_doneDay[i] = today; continue; }

      double bid = SymbolInfoDouble(sym, SYMBOL_BID), ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      if(bid <= 0 || ask <= 0) continue;
      if((ask - bid) / ((ask + bid) / 2) * 100.0 > InpMaxSpreadPct) continue;   // retry later today

      int sCur = (cur > 0) ? 1 : (cur < 0 ? -1 : 0);
      int sTgt = (tgtSigned > 0) ? 1 : (tgtSigned < 0 ? -1 : 0);
      bool need = (sCur != sTgt) || MathAbs(tgtW - curW) > InpRebalBuffer * MathAbs(tgtW);
      bool ok = true;
      if(need)
      {
         if(sCur != sTgt)
         {
            if(sCur != 0) ok = CloseAll(sym);
            if(ok && sTgt != 0) ok = Open(sym, tgtLots, sTgt > 0);
         }
         else
         {
            double d = MathAbs(tgtSigned) - MathAbs(cur);
            double dl = NormLots(sym, MathAbs(d));
            if(dl > 0) ok = (d > 0) ? Open(sym, dl, sTgt > 0) : Reduce(sym, dl);
         }
      }
      if(ok) g_doneDay[i] = today;
   }
   Comment(report);
   if(InpVerbose) Print(report);
}

//+------------------------------------------------------------------+
//| Stop-out detection -> cooldown                                     |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &req, const MqlTradeResult &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_REASON) != DEAL_REASON_SL) return;
   string sym = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   for(int i = 0; i < g_n; i++)
      if(g_sym[i] == sym)
      {
         // weekdays -> calendar days
         g_coolUntil[i] = TimeCurrent() + (datetime)((InpCooldownDays * 7 / 5 + 1) * 86400);
         GlobalVariableSet(g_gv + "cool_" + sym, (double)g_coolUntil[i]);
         PrintFormat("%s: hard stop hit, cooldown until %s", sym, TimeToString(g_coolUntil[i]));
      }
}

//+------------------------------------------------------------------+
//| Custom optimisation criterion for MT5 tester / forward test       |
//| = annualised-return proxy / max equity drawdown, penalised when   |
//|   there are too few trades to be statistically meaningful         |
//+------------------------------------------------------------------+
double OnTester()
{
   double profit = TesterStatistics(STAT_PROFIT);
   double ddPct  = TesterStatistics(STAT_EQUITYDD_PERCENT);
   double trades = TesterStatistics(STAT_TRADES);
   if(trades < 30 || ddPct <= 0) return 0;
   double init = TesterStatistics(STAT_INITIAL_DEPOSIT);
   double retPct = profit / init * 100.0;
   return retPct / ddPct;
}
//+------------------------------------------------------------------+
