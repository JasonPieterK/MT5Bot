//+------------------------------------------------------------------+
//|                                        MT5BotStatusPanel.mq5      |
//|                                                                    |
//| Read-only on-chart mirror of the MT5 Bot Python app's status.     |
//| This EA places NO orders, modifies NO positions, and calls NO     |
//| trade functions whatsoever. It only reads a status file the       |
//| Python app writes every ~5s and draws a small panel on the chart. |
//| Safe to attach to any chart, on any symbol/timeframe -- it does   |
//| not need to match the symbol the bot is trading.                  |
//+------------------------------------------------------------------+
#property copyright "MT5 Bot"
#property strict
#property indicator_chart_window
#property indicator_plots 0

input int RefreshSeconds = 1;   // how often to re-read the status file
input int StaleAfterSeconds = 15; // flag the panel as stale if the file is older than this

string StatusFile = "mt5_bot_status.txt";
string PanelPrefix = "MT5BotPanel_";

string gKeys[];
string gVals[];

//+------------------------------------------------------------------+
int OnInit()
  {
   CreatePanel();
   EventSetTimer(RefreshSeconds);
   RefreshPanel();
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
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
bool LoadStatus()
  {
   ArrayResize(gKeys, 0);
   ArrayResize(gVals, 0);

   if(!FileIsExist(StatusFile, FILE_COMMON))
      return(false);

   int handle = FileOpen(StatusFile, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return(false);

   while(!FileIsEnding(handle))
     {
      string line = FileReadString(handle);
      int eq = StringFind(line, "=");
      if(eq > 0)
        {
         string k = StringSubstr(line, 0, eq);
         string v = StringSubstr(line, eq + 1);
         int n = ArraySize(gKeys);
         ArrayResize(gKeys, n + 1);
         ArrayResize(gVals, n + 1);
         gKeys[n] = k;
         gVals[n] = v;
        }
     }
   FileClose(handle);
   return(true);
  }

//+------------------------------------------------------------------+
string GetVal(string key, string def = "")
  {
   for(int i = 0; i < ArraySize(gKeys); i++)
      if(gKeys[i] == key)
         return(gVals[i]);
   return(def);
  }

//+------------------------------------------------------------------+
void CreateLabel(string name, int y)
  {
   ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 18);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrBlack);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

//+------------------------------------------------------------------+
void CreatePanel()
  {
   string bg = PanelPrefix + "bg";
   ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, bg, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, 20);
   ObjectSetInteger(0, bg, OBJPROP_XSIZE, 230);
   ObjectSetInteger(0, bg, OBJPROP_YSIZE, 150);
   ObjectSetInteger(0, bg, OBJPROP_BGCOLOR, clrWhiteSmoke);
   ObjectSetInteger(0, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, bg, OBJPROP_COLOR, clrBlack);
   ObjectSetInteger(0, bg, OBJPROP_BACK, false);
   ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, bg, OBJPROP_HIDDEN, true);

   CreateLabel(PanelPrefix + "title", 26);
   CreateLabel(PanelPrefix + "status", 46);
   CreateLabel(PanelPrefix + "strategy", 66);
   CreateLabel(PanelPrefix + "symbol", 86);
   CreateLabel(PanelPrefix + "equity", 106);
   CreateLabel(PanelPrefix + "positions", 126);
   CreateLabel(PanelPrefix + "updated", 146);

   ObjectSetString(0, PanelPrefix + "title", OBJPROP_TEXT, "MT5 BOT");
   ObjectSetInteger(0, PanelPrefix + "title", OBJPROP_FONTSIZE, 11);
  }

//+------------------------------------------------------------------+
void RefreshPanel()
  {
   bool ok = LoadStatus();

   if(!ok)
     {
      ObjectSetString(0, PanelPrefix + "status", OBJPROP_TEXT, "Status: app not found");
      ObjectSetInteger(0, PanelPrefix + "status", OBJPROP_COLOR, clrGray);
      ObjectSetString(0, PanelPrefix + "strategy", OBJPROP_TEXT, "");
      ObjectSetString(0, PanelPrefix + "symbol", OBJPROP_TEXT, "");
      ObjectSetString(0, PanelPrefix + "equity", OBJPROP_TEXT, "");
      ObjectSetString(0, PanelPrefix + "positions", OBJPROP_TEXT, "");
      ObjectSetString(0, PanelPrefix + "updated", OBJPROP_TEXT, "Start the MT5 Bot app");
      ChartRedraw(0);
      return;
     }

   long updatedUnix = (long)StringToInteger(GetVal("last_update_unix", "0"));
   long ageSec = (long)TimeGMT() - updatedUnix;
   bool stale = (updatedUnix == 0 || ageSec > StaleAfterSeconds);

   bool autoOn = (GetVal("auto_enabled", "0") == "1");
   bool watchlistOn = (GetVal("watchlist_enabled", "0") == "1");
   bool live = (autoOn || watchlistOn);

   string statusText = stale ? "Status: stale" : (live ? "Status: LIVE" : "Status: idle");
   color statusColor = stale ? clrGray : (live ? clrCrimson : clrDarkGreen);
   ObjectSetString(0, PanelPrefix + "status", OBJPROP_TEXT, statusText);
   ObjectSetInteger(0, PanelPrefix + "status", OBJPROP_COLOR, statusColor);

   string mode = watchlistOn ? "watchlist" : GetVal("active_strategy", "-");
   ObjectSetString(0, PanelPrefix + "strategy", OBJPROP_TEXT, "Strategy: " + mode);
   ObjectSetString(0, PanelPrefix + "symbol", OBJPROP_TEXT,
                    "Symbol: " + GetVal("symbol", "-") + " / " + GetVal("timeframe", "-"));
   ObjectSetString(0, PanelPrefix + "equity", OBJPROP_TEXT, "Equity: " + GetVal("equity", "-"));
   ObjectSetString(0, PanelPrefix + "positions", OBJPROP_TEXT,
                    "Open positions: " + GetVal("open_positions", "-"));
   ObjectSetString(0, PanelPrefix + "updated", OBJPROP_TEXT,
                    (stale ? "Last update: " : "Updated: ") + (string)ageSec + "s ago" + (stale ? " (stale)" : ""));

   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
