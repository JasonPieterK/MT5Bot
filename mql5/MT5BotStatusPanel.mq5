//+------------------------------------------------------------------+
//|                                        MT5BotStatusPanel.mq5      |
//|                                                                    |
//| Read-only on-chart mirror of the MT5 Bot Python app's status.     |
//| This EA places NO orders, modifies NO positions, and calls NO     |
//| trade function whatsoever. Grep this file: there is no OrderSend, |
//| OrderModify, OrderClose, CTrade or MqlTradeRequest anywhere in it,|
//| and nothing may ever add one. It reads a status file the Python   |
//| app writes every ~5s and draws a panel on the chart. Safe to      |
//| attach to any chart, on any symbol/timeframe -- it does not need  |
//| to match the symbol the bot is trading.                           |
//+------------------------------------------------------------------+
#property copyright "MT5 Bot"
#property version   "2.00"
#property strict
#property description "Read-only status mirror for the MT5 Bot Python app."
#property description "Never places, modifies or closes any order."

// No #property indicator_* here on purpose. Those were left over from an earlier draft and
// forced the compiler to treat this as a custom indicator, which then demands an
// OnCalculate(). It is an Expert Advisor (it lives in MQL5/Experts and uses OnTimer), so
// the indicator properties are simply wrong.

//--- Graphite & Amber -- the same palette as the web dashboard, so the chart panel and the
//--- browser read as one product. C'r,g,b' literals take the channels in RGB source order
//--- and MQL5 does the BGR packing itself, so these are the dashboard hex values pasted
//--- straight in with no hand-swapped bytes to get wrong.
#define CLR_SURFACE  C'23,26,32'     // #171A20  panel body
#define CLR_RAISED   C'30,34,42'     // #1E222A  grouped/raised rows
#define CLR_BORDER   C'42,48,59'     // #2A303B  hairlines and frame
#define CLR_MUTED    C'155,163,175'  // #9BA3AF  row labels, de-emphasised values
#define CLR_TEXT     C'230,232,236'  // #E6E8EC  live values
#define CLR_AMBER    C'245,165,36'   // #F5A524  armed state + headings (used sparingly)
#define CLR_GREEN    C'34,197,94'    // #22C55E  at peak / profit
#define CLR_RED      C'239,68,68'    // #EF4444  stale, offline, drawdown

//--- Row slots. Named so the layout maths and the refresh code can never drift apart.
#define ROW_MODE       0
#define ROW_STRATEGY   1
#define ROW_SYMBOL     2
#define ROW_EQUITY     3
#define ROW_DRAWDOWN   4
#define ROW_POSITIONS  5
#define ROW_COUNT      6

#define MAX_KEYS      32   // the status file has ~10 keys; this is headroom, not a limit

input ENUM_BASE_CORNER InpCorner            = CORNER_LEFT_UPPER; // Panel corner
input int              InpOffsetX           = 12;   // X offset from that corner (px)
input int              InpOffsetY           = 22;   // Y offset from that corner (px)
input int              InpFontSize          = 9;    // Font size (pt, 6-16)
input int              InpRefreshSeconds    = 1;    // Re-read the status file every N sec
input int              InpStaleAfterSeconds = 15;   // Call the data stale after N sec
input double           InpDrawdownAlertPct  = 5.0;  // Turn drawdown red past this %

const string StatusFile  = "mt5_bot_status.txt";
const string PanelPrefix = "MT5BotPanel_";

string gRowLabel[ROW_COUNT] = {"Mode", "Strategy", "Symbol", "Equity", "Drawdown", "Positions"};

string gKeys[MAX_KEYS];
string gVals[MAX_KEYS];
int    gCount = 0;

//--- Layout, all in pixels and all recomputed by BuildPanel().
int gFontSize, gStaleSecs;
int gPanelW, gPanelH, gOriginX, gOriginY;
int gRowH, gHeaderH, gPad, gGap;
int gRowY[ROW_COUNT];
int gDivY[2];
int gStatsY, gStatsH, gFootY;

//+------------------------------------------------------------------+
int OnInit()
  {
   gStaleSecs = InpStaleAfterSeconds;
   if(gStaleSecs < 3)
      gStaleSecs = 3;

   BuildPanel();

   int secs = InpRefreshSeconds;
   if(secs < 1)
      secs = 1;   // EventSetTimer(0) is rejected outright and the panel would never update
   EventSetTimer(secs);

   RefreshPanel();
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   // Every object this EA creates is named with PanelPrefix, so one prefixed sweep is a
   // complete cleanup -- removing the EA must not leave orphans behind on the chart.
   ObjectsDeleteAll(0, PanelPrefix);
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   RefreshPanel();
  }

//+------------------------------------------------------------------+
// Intentionally empty -- this EA never acts on ticks. It is a status
// display only; all trading logic lives in the Python app.
void OnTick()
  {
  }

//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   // CHART_CHANGE covers resize, timeframe switches and scale changes. The panel is drawn in
   // absolute pixels, so a bottom- or right-anchored panel has to be re-placed when the chart
   // window changes size or it drifts off the edge.
   if(id == CHARTEVENT_CHART_CHANGE)
     {
      BuildPanel();
      RefreshPanel();
     }
  }

//+------------------------------------------------------------------+
//| Layout                                                            |
//+------------------------------------------------------------------+
void ComputeLayout()
  {
   gFontSize = InpFontSize;
   if(gFontSize < 6)  gFontSize = 6;
   if(gFontSize > 16) gFontSize = 16;

   gRowH    = gFontSize + 11;
   gHeaderH = gRowH + 8;
   gPad     = 9;
   gGap     = 7;

   // Width tracks the font so a bigger font does not clip the values off the right edge.
   gPanelW = gFontSize * 26;
   if(gPanelW < 200)
      gPanelW = 200;

   int y = gHeaderH;
   gDivY[0] = y;
   y += 1 + gGap;

   for(int i = ROW_MODE; i <= ROW_SYMBOL; i++)
     {
      gRowY[i] = y;
      y += gRowH;
     }

   y += gGap;
   gStatsY = y;                    // raised block groups the three numbers together
   gStatsH = 3 * gRowH + 8;
   y += 4;
   for(int j = ROW_EQUITY; j <= ROW_POSITIONS; j++)
     {
      gRowY[j] = y;
      y += gRowH;
     }
   y += 4 + gGap;

   gDivY[1] = y;
   y += 1 + gGap;

   gFootY = y;
   y += gRowH;

   gPanelH = y + gPad;
  }

//+------------------------------------------------------------------+
void ComputeOrigin()
  {
   int cw = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS, 0);
   int ch = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS, 0);

   bool right = (InpCorner == CORNER_RIGHT_UPPER || InpCorner == CORNER_RIGHT_LOWER);
   bool lower = (InpCorner == CORNER_LEFT_LOWER  || InpCorner == CORNER_RIGHT_LOWER);

   // Everything below is drawn from CORNER_LEFT_UPPER in absolute pixels. Converting the
   // user's chosen corner here, once, keeps a single coordinate system for all 20+ objects --
   // otherwise every right-aligned value would flip sides when the panel moves to the right
   // corner, because MQL5 grows X leftwards from a right-hand corner.
   gOriginX = right ? cw - InpOffsetX - gPanelW : InpOffsetX;
   gOriginY = lower ? ch - InpOffsetY - gPanelH : InpOffsetY;

   // cw/ch read 0 while the chart is still opening; clamping keeps the panel on-screen until
   // the first CHART_CHANGE gives us real dimensions.
   if(gOriginX < 0) gOriginX = 0;
   if(gOriginY < 0) gOriginY = 0;
  }

//+------------------------------------------------------------------+
//| Object helpers                                                    |
//+------------------------------------------------------------------+
void EnsureObject(const string name, ENUM_OBJECT objType)
  {
   // Create-if-absent, then always re-apply properties. Repeated calls update the existing
   // object instead of piling up new ones, so OnTimer/CHART_CHANGE never leak.
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, objType, 0, 0, 0);

   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 0);
  }

//+------------------------------------------------------------------+
void PlaceRect(const string name, int x, int y, int w, int h, color bg, color frame)
  {
   EnsureObject(name, OBJ_RECTANGLE_LABEL);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, gOriginX + x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, gOriginY + y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_COLOR, frame);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
  }

//+------------------------------------------------------------------+
void PlaceText(const string name, int x, int y, ENUM_ANCHOR_POINT anchor,
               const string font, int size, color clr)
  {
   EnsureObject(name, OBJ_LABEL);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, gOriginX + x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, gOriginY + y);
   // ANCHOR_LEFT / ANCHOR_RIGHT anchor on the text's vertical centre, so rows stay centred
   // at any font size without a hand-tuned baseline fudge.
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, anchor);
   ObjectSetString(0, name, OBJPROP_FONT, font);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
  }

//+------------------------------------------------------------------+
string RowKey(int i) { return(PanelPrefix + "k" + IntegerToString(i)); }
string RowVal(int i) { return(PanelPrefix + "v" + IntegerToString(i)); }

//+------------------------------------------------------------------+
void BuildPanel()
  {
   ComputeLayout();
   ComputeOrigin();

   // Rectangles first: MT5 draws chart objects in creation order, so the background has to
   // exist before the labels that sit on top of it.
   PlaceRect(PanelPrefix + "bg",    0, 0, gPanelW, gPanelH, CLR_SURFACE, CLR_BORDER);
   PlaceRect(PanelPrefix + "hdr",   1, 1, gPanelW - 2, gHeaderH - 1, CLR_RAISED, CLR_RAISED);
   PlaceRect(PanelPrefix + "div0",  1, gDivY[0], gPanelW - 2, 1, CLR_BORDER, CLR_BORDER);
   PlaceRect(PanelPrefix + "stats", gPad - 3, gStatsY, gPanelW - 2 * (gPad - 3), gStatsH,
             CLR_RAISED, CLR_RAISED);
   PlaceRect(PanelPrefix + "div1",  gPad, gDivY[1], gPanelW - 2 * gPad, 1, CLR_BORDER, CLR_BORDER);
   // A colour chip beside the title: peripheral vision catches a red dot long before it
   // reads the word next to it.
   PlaceRect(PanelPrefix + "dot",   gPad, gHeaderH / 2 - 3, 6, 6, CLR_MUTED, CLR_MUTED);

   PlaceText(PanelPrefix + "title", gPad + 13, gHeaderH / 2, ANCHOR_LEFT,
             "Segoe UI", gFontSize + 1, CLR_AMBER);
   ObjectSetString(0, PanelPrefix + "title", OBJPROP_TEXT, "MT5 BOT");

   PlaceText(PanelPrefix + "status", gPanelW - gPad, gHeaderH / 2, ANCHOR_RIGHT,
             "Segoe UI", gFontSize, CLR_MUTED);

   for(int i = 0; i < ROW_COUNT; i++)
     {
      int cy = gRowY[i] + gRowH / 2;
      PlaceText(RowKey(i), gPad + 4, cy, ANCHOR_LEFT, "Segoe UI", gFontSize, CLR_MUTED);
      ObjectSetString(0, RowKey(i), OBJPROP_TEXT, gRowLabel[i]);
      // Values right-aligned in Consolas: fixed-width digits make the numeric column scan
      // vertically instead of jittering as values change length.
      PlaceText(RowVal(i), gPanelW - gPad - 4, cy, ANCHOR_RIGHT, "Consolas", gFontSize, CLR_TEXT);
     }

   PlaceText(PanelPrefix + "foot", gPad + 4, gFootY + gRowH / 2, ANCHOR_LEFT,
             "Segoe UI", gFontSize, CLR_MUTED);
  }

//+------------------------------------------------------------------+
//| Status file                                                       |
//+------------------------------------------------------------------+
string Trim(string s)
  {
   // StringTrimLeft/Right mutate in place and return a count, not a string -- they cannot be
   // chained. They also strip CR/LF, which is what we want: Python writes the file in text
   // mode, so every line arrives with a trailing \r on Windows.
   StringTrimLeft(s);
   StringTrimRight(s);
   return(s);
  }

//+------------------------------------------------------------------+
//| Returns the number of key=value pairs read, or -1 if the file is  |
//| missing or could not be opened.                                   |
//+------------------------------------------------------------------+
int LoadStatus()
  {
   gCount = 0;

   if(!FileIsExist(StatusFile, FILE_COMMON))
      return(-1);

   int handle = FileOpen(StatusFile, FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return(-1);   // the app rewrites this file in place; a read that lands mid-write just
                    // fails here and the next timer tick picks up the finished file

   while(!FileIsEnding(handle) && gCount < MAX_KEYS)
     {
      string line = Trim(FileReadString(handle));
      int eq = StringFind(line, "=");
      if(eq <= 0)
         continue;   // blank line or a truncated write -- skip rather than store garbage

      gKeys[gCount] = StringSubstr(line, 0, eq);
      gVals[gCount] = Trim(StringSubstr(line, eq + 1));
      gCount++;
     }

   FileClose(handle);
   return(gCount);
  }

//+------------------------------------------------------------------+
string GetVal(const string key, const string def)
  {
   for(int i = 0; i < gCount; i++)
      if(gKeys[i] == key)
         return(gVals[i]);
   return(def);
  }

//+------------------------------------------------------------------+
string StrOr(const string s, const string def)
  {
   return(StringLen(s) > 0 ? s : def);
  }

//+------------------------------------------------------------------+
string AgeText(long secs)
  {
   if(secs < 60)   return(IntegerToString(secs) + "s ago");
   if(secs < 3600) return(IntegerToString(secs / 60) + "m ago");
   return(IntegerToString(secs / 3600) + "h ago");
  }

//+------------------------------------------------------------------+
//| Rendering                                                         |
//+------------------------------------------------------------------+
void SetRow(int row, const string text, color clr)
  {
   ObjectSetString(0, RowVal(row), OBJPROP_TEXT, text);
   ObjectSetInteger(0, RowVal(row), OBJPROP_COLOR, clr);
  }

//+------------------------------------------------------------------+
void SetHeader(const string pill, color clr)
  {
   ObjectSetString(0, PanelPrefix + "status", OBJPROP_TEXT, pill);
   ObjectSetInteger(0, PanelPrefix + "status", OBJPROP_COLOR, clr);
   ObjectSetInteger(0, PanelPrefix + "dot", OBJPROP_BGCOLOR, clr);
   ObjectSetInteger(0, PanelPrefix + "dot", OBJPROP_COLOR, clr);
   // The whole frame takes the status colour too, so a broken feed is visible from across
   // the room and can't be mistaken for a healthy panel with one small word changed. Idle is
   // the exception -- nothing is wrong, so it keeps the neutral border.
   color frame = CLR_BORDER;
   if(clr != CLR_MUTED)
      frame = clr;
   ObjectSetInteger(0, PanelPrefix + "bg", OBJPROP_COLOR, frame);
  }

//+------------------------------------------------------------------+
void SetFooter(const string text, color clr)
  {
   ObjectSetString(0, PanelPrefix + "foot", OBJPROP_TEXT, text);
   ObjectSetInteger(0, PanelPrefix + "foot", OBJPROP_COLOR, clr);
  }

//+------------------------------------------------------------------+
void ShowProblem(const string pill, const string footer)
  {
   SetHeader(pill, CLR_RED);
   SetFooter(footer, CLR_RED);
   for(int i = 0; i < ROW_COUNT; i++)
      SetRow(i, "-", CLR_MUTED);
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
void RefreshPanel()
  {
   int pairs = LoadStatus();
   if(pairs < 0)
     {
      ShowProblem("OFFLINE", "No data from MT5 Bot -- app not running");
      return;
     }
   if(pairs == 0)
     {
      ShowProblem("NO DATA", "Status file present but empty");
      return;
     }

   long updated = (long)StringToInteger(GetVal("last_update_unix", "0"));
   if(updated <= 0)
     {
      ShowProblem("NO DATA", "Status file unreadable");
      return;
     }

   long age = (long)TimeGMT() - updated;
   if(age < 0)
      age = 0;   // terminal clock running ahead of the app's -- don't render "-4s ago"
   bool stale = (age > gStaleSecs);

   string mode = GetVal("trading_mode", "");
   if(StringLen(mode) == 0)
     {
      // Status files written before trading_mode existed only carried the two flags. Deriving
      // the mode here keeps an older app from making the panel read "off" while it trades.
      if(GetVal("watchlist_enabled", "0") == "1")      mode = "watchlist";
      else if(GetVal("auto_enabled", "0") == "1")      mode = "single";
      else                                             mode = "off";
     }
   bool armed = (mode == "single" || mode == "watchlist");

   if(stale)
      SetHeader("STALE", CLR_RED);
   else if(armed)
      SetHeader("ARMED", CLR_AMBER);
   else
      SetHeader("IDLE", CLR_MUTED);

   // Stale numbers must not look authoritative: greying every value is what stops someone
   // reading a five-minute-old equity figure as the current one.
   color valueClr = stale ? CLR_MUTED : CLR_TEXT;

   color modeClr = CLR_MUTED;
   if(armed && !stale)
      modeClr = CLR_AMBER;
   SetRow(ROW_MODE, mode, modeClr);

   SetRow(ROW_STRATEGY, StrOr(GetVal("active_strategy", ""), "-"), valueClr);

   string symbolText = StrOr(GetVal("symbol", ""), "-") + " " + GetVal("timeframe", "");
   SetRow(ROW_SYMBOL, Trim(symbolText), valueClr);

   double equity = StringToDouble(GetVal("equity", "0"));
   SetRow(ROW_EQUITY, DoubleToString(equity, 2), valueClr);

   double dd = StringToDouble(GetVal("drawdown_percent", "0"));
   bool atPeak = (dd < 0.01);
   color ddClr = valueClr;
   if(!stale)
     {
      if(atPeak)                         ddClr = CLR_GREEN;   // sitting at the high-water mark
      else if(dd >= InpDrawdownAlertPct) ddClr = CLR_RED;
     }
   string ddText = "at peak";
   if(!atPeak)
      ddText = "-" + DoubleToString(dd, 2) + "%";
   SetRow(ROW_DRAWDOWN, ddText, ddClr);

   long openCount = (long)StringToInteger(GetVal("open_positions", "0"));
   color openClr = CLR_TEXT;
   if(stale || openCount == 0)
      openClr = CLR_MUTED;
   SetRow(ROW_POSITIONS, IntegerToString(openCount), openClr);

   if(stale)
      SetFooter("NO UPDATE FOR " + AgeText(age) + " -- app stopped?", CLR_RED);
   else
      SetFooter("Updated " + AgeText(age), CLR_MUTED);

   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
