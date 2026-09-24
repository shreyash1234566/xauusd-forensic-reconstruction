//+------------------------------------------------------------------+
//|                                Phase8E_Forensic_Reconstructed_EA.mq5 |
//|                        Forensic Reconstruction of XAUUSD.f Strategy |
//|                                      Strict Single-Position Scalper |
//+------------------------------------------------------------------+
#property copyright "Forensic Reverse Engineering Engine"
#property link      "https://anthropic.com"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//--- Input Parameters
input group "=== Model A: Supervisory & Eligibility Envelope ==="
input int      InpStartHour         = 5;        // Session Start Hour (UTC)
input int      InpEndHour           = 16;       // Session End Hour (UTC)
input int      InpFridayStopHour    = 20;       // Friday Lockout Hour (UTC)
input int      InpCooldownSeconds   = 120;      // Inter-Trade Cooldown (Seconds)
input double   InpMinH1ATRPct       = 0.25;     // Min H1 ATR % Filter

input group "=== Model B: Microstructure Trigger ==="
input double   InpMomentumThresh    = 0.30;     // Price Momentum Threshold ($)
input int      InpLookbackTicks     = 50;       // Tick Buffer Depth
input double   InpMaxSpread         = 1.00;     // Max Spread Allowed ($)

input group "=== Execution & Risk Management ==="
input double   InpBaseLot           = 0.01;     // Fixed Base Lot Size
input double   InpTakeProfitDollars = 1.80;     // Take Profit Distance ($)
input double   InpStopLossDollars   = 2.50;     // Stop Loss Distance ($)
input int      InpMaxHoldMinutes    = 12;       // Max Holding Duration (Minutes)
input ulong    InpMagicNumber       = 888423;   // Magic Number

//--- Global Latent State Tracking
datetime g_last_close_time = 0;
datetime g_current_entry_time = 0;
int      g_h1_atr_handle = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetMarginMode();
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   g_h1_atr_handle = iATR(_Symbol, PERIOD_H1, 14);
   if(g_h1_atr_handle == INVALID_HANDLE)
   {
      Print("[ERROR] Failed to initialize H1 ATR indicator handle.");
      return(INIT_FAILED);
   }

   Print("[INIT] Phase 8E Forensic Reconstructed EA Initialized Successfully.");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_h1_atr_handle != INVALID_HANDLE)
      IndicatorRelease(g_h1_atr_handle);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt);

   // 1. Check Active Open Positions
   int total_positions = PositionsTotal();
   if(total_positions > 0)
   {
      // Check Time-based Exit
      for(int i = total_positions - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         {
            datetime pos_time = (datetime)PositionGetInteger(POSITION_TIME);
            if((now - pos_time) >= (InpMaxHoldMinutes * 60))
            {
               trade.PositionClose(ticket);
               g_last_close_time = now;
               Print("[EXIT] Max Duration Reached (", InpMaxHoldMinutes, " min). Closed Ticket: ", ticket);
            }
         }
      }
      return; // Single-position lockout active
   }

   // 2. Model A: Execution Eligibility Gate
   // Session Window (05:00 - 16:00 UTC)
   if(dt.hour < InpStartHour || dt.hour > InpEndHour)
      return;

   // Friday Weekend Lockout (Post-20:00 UTC)
   if(dt.day_of_week == 5 && dt.hour >= InpFridayStopHour)
      return;

   // Cooldown Lockout (120s post-close)
   if(g_last_close_time > 0 && (now - g_last_close_time) < InpCooldownSeconds)
      return;

   // Volatility Filter (H1 ATR >= 0.25%)
   double atr_val[];
   ArraySetAsSeries(atr_val, true);
   if(CopyBuffer(g_h1_atr_handle, 0, 0, 1, atr_val) <= 0)
      return;

   MqlTick current_tick;
   if(!SymbolInfoTick(_Symbol, current_tick))
      return;

   double atr_pct = (atr_val[0] / current_tick.bid) * 100.0;
   if(atr_pct < InpMinH1ATRPct)
      return;

   // Floating Spread Check
   double current_spread = current_tick.ask - current_tick.bid;
   if(current_spread > InpMaxSpread)
      return;

   // 3. Model B: Microstructure Momentum Trigger
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, PERIOD_M1, 0, 2, rates) < 2)
      return;

   double ret1 = rates[0].close - rates[1].close;
   double abs_ret1 = MathAbs(ret1);

   // Edge Trigger Condition
   if(abs_ret1 >= InpMomentumThresh)
   {
      double lot = InpBaseLot;
      if(ret1 > 0)
      {
         // BUY Order
         double sl = current_tick.ask - InpStopLossDollars;
         double tp = current_tick.ask + InpTakeProfitDollars;
         if(trade.Buy(lot, _Symbol, current_tick.ask, sl, tp, "Phase8E Reconstructed BUY"))
         {
            g_current_entry_time = now;
            Print("[ENTRY] BUY Executed @ ", current_tick.ask, " | SL: ", sl, " | TP: ", tp);
         }
      }
      else
      {
         // SELL Order
         double sl = current_tick.bid + InpStopLossDollars;
         double tp = current_tick.bid - InpTakeProfitDollars;
         if(trade.Sell(lot, _Symbol, current_tick.bid, sl, tp, "Phase8E Reconstructed SELL"))
         {
            g_current_entry_time = now;
            Print("[ENTRY] SELL Executed @ ", current_tick.bid, " | SL: ", sl, " | TP: ", tp);
         }
      }
   }
}
//+------------------------------------------------------------------+
