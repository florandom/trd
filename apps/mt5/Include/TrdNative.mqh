// Native MT5 connection for local observation only. No trading or HTTP API.
#ifndef TRD_NATIVE_MQH
#define TRD_NATIVE_MQH
#include "TrdCore.mqh"

string trd_native_status="DISABLED",trd_native_fault="",trd_native_snapshot="",trd_native_chain="",trd_native_binding="";
long trd_native_sequence=0;
int trd_native_file=INVALID_HANDLE;
struct TrdNativeHint { MqlTradeTransaction transaction;MqlTradeResult result;long observed_at; };
TrdNativeHint trd_native_hints[128];int trd_native_hint_count=0;

string TrdNativeStamp(const long second)
{
   string s=TimeToString((datetime)second,TIME_DATE|TIME_SECONDS);
   StringReplace(s,".","-");StringReplace(s," ","T");return s+"+00:00";
}
bool TrdNativeFail(const string reason,const bool permanent=false)
{
   trd_native_status=reason;trd_native_snapshot="";
   if(permanent) trd_native_fault=reason;
   return false;
}
bool TrdNativeNumber(const double value,string &text)
{
   if(!MathIsValidNumber(value)||MathAbs(value)>1000000000000.0) return false;
   text=DoubleToString(value==0?0:value,16);
   if(value!=0&&(text=="0.0000000000000000"||text=="-0.0000000000000000")) return false;
   return StringLen(text)<=32;
}
string TrdNativeDouble(const double value)
{
   string text;return TrdNativeNumber(value,text)?TrdQuote(text):"";
}
bool TrdNativeText(const string value,const bool empty=false)
{
   return (empty||StringLen(value)>0)&&StringLen(value)<=128&&TrdQuote(value)!="";
}
bool TrdNativeIdentity()
{
   ResetLastError();
   long login=AccountInfoInteger(ACCOUNT_LOGIN),mode=AccountInfoInteger(ACCOUNT_TRADE_MODE);
   string server=AccountInfoString(ACCOUNT_SERVER);
   if(GetLastError()!=0||IntegerToString(login)!=NativeExpectedLogin||server!=NativeExpectedServer||
      login<1||mode!=ACCOUNT_TRADE_MODE_DEMO) return TrdNativeFail("NATIVE_ACCOUNT_MISMATCH",true);
   return true;
}
bool TrdNativePositions(string &json)
{
   int count=PositionsTotal();if(count<0||count>64) return TrdNativeFail("NATIVE_POSITION_CAPACITY");
   json="[";
   for(int i=0;i<count;i++)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0||ticket>(ulong)9223372036854775807||StringFind(json,"\"ticket\":"+TrdQuote(IntegerToString((long)ticket))+",")>=0||
         !PositionSelectByTicket(ticket)) return TrdNativeFail("NATIVE_POSITION_READ_FAILED");
      long identity,magic,side;double volume,entry,sl,tp;string symbol;
      if(!PositionGetInteger(POSITION_IDENTIFIER,identity)||!PositionGetInteger(POSITION_MAGIC,magic)||
         !PositionGetInteger(POSITION_TYPE,side)||!PositionGetString(POSITION_SYMBOL,symbol)||
         !PositionGetDouble(POSITION_VOLUME,volume)||!PositionGetDouble(POSITION_PRICE_OPEN,entry)||
         !PositionGetDouble(POSITION_SL,sl)||!PositionGetDouble(POSITION_TP,tp)||identity<1||magic<0||
         (side!=POSITION_TYPE_BUY&&side!=POSITION_TYPE_SELL)||!TrdNativeText(symbol)||volume<=0||entry<=0||sl<0||tp<0||
         TrdNativeDouble(volume)==""||TrdNativeDouble(entry)==""||TrdNativeDouble(sl)==""||TrdNativeDouble(tp)=="") return TrdNativeFail("NATIVE_POSITION_READ_FAILED");
      if(i>0) json+=",";
      json+="{\"ticket\":"+TrdQuote(IntegerToString((long)ticket))+",\"identifier\":"+TrdQuote(IntegerToString(identity))+
         ",\"magic\":"+TrdQuote(IntegerToString(magic))+",\"symbol\":"+TrdQuote(symbol)+",\"side\":"+TrdQuote(side==POSITION_TYPE_BUY?"BUY":"SELL")+
         ",\"volume\":"+TrdNativeDouble(volume)+",\"entry\":"+TrdNativeDouble(entry)+",\"sl\":"+TrdNativeDouble(sl)+",\"tp\":"+TrdNativeDouble(tp)+",\"ownership_verified\":false}";
   }
   json+="]";return PositionsTotal()==count?true:TrdNativeFail("NATIVE_PORTFOLIO_CHANGED");
}
bool TrdNativeResolvePosition(const string identifier,ulong &ticket)
{
   ticket=0;long id;
   if(trd_native_fault!=""||!ActivateNativeReadOnly||!TrdUnsigned(identifier,id)||id<1||!TrdNativeIdentity()) return false;
   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) return TrdNativeFail("NATIVE_DISCONNECTED");
   string positions;if(!TrdNativePositions(positions)) return false;
   TrdJson doc;if(!doc.Parse("{\"positions\":"+positions+"}")) return false;
   int owner=doc.Field("positions"),matches=0;
   for(int i=owner+1;i<doc.count;i++) if(doc.parent[i]==owner&&doc.Get("identifier",i)==identifier)
   {
      long current;if(!TrdUnsigned(doc.Get("ticket",i),current)||current<1) return false;
      ticket=(ulong)current;matches++;
   }
   if(matches!=1) { ticket=0;return false; }
   if(!TrdNativeIdentity()) { ticket=0;return false; }
   return true; // Current ticket resolution grants no ownership or execution authority.
}
bool TrdNativeOrders(string &json,const bool history=false)
{
   int count=history?HistoryOrdersTotal():OrdersTotal();
   if(count<0||count>(history?128:64)) return TrdNativeFail("NATIVE_ORDER_CAPACITY");
   json="[";
   for(int i=0;i<count;i++)
   {
      ulong ticket=history?HistoryOrderGetTicket(i):OrderGetTicket(i);
      if(ticket==0||ticket>(ulong)9223372036854775807||StringFind(json,"\"ticket\":"+TrdQuote(IntegerToString((long)ticket))+",")>=0||
         (!history&&!OrderSelect(ticket))) return TrdNativeFail("NATIVE_ORDER_READ_FAILED");
      long identity,magic,type,state;double volume,price,sl,tp;string symbol;
      bool ok=history?
         HistoryOrderGetInteger(ticket,ORDER_POSITION_ID,identity)&&HistoryOrderGetInteger(ticket,ORDER_MAGIC,magic)&&
         HistoryOrderGetInteger(ticket,ORDER_TYPE,type)&&HistoryOrderGetInteger(ticket,ORDER_STATE,state)&&HistoryOrderGetString(ticket,ORDER_SYMBOL,symbol)&&
         HistoryOrderGetDouble(ticket,ORDER_VOLUME_INITIAL,volume)&&HistoryOrderGetDouble(ticket,ORDER_PRICE_OPEN,price)&&
         HistoryOrderGetDouble(ticket,ORDER_SL,sl)&&HistoryOrderGetDouble(ticket,ORDER_TP,tp):
         OrderGetInteger(ORDER_POSITION_ID,identity)&&OrderGetInteger(ORDER_MAGIC,magic)&&OrderGetInteger(ORDER_TYPE,type)&&
         OrderGetInteger(ORDER_STATE,state)&&OrderGetString(ORDER_SYMBOL,symbol)&&OrderGetDouble(ORDER_VOLUME_CURRENT,volume)&&
         OrderGetDouble(ORDER_PRICE_OPEN,price)&&OrderGetDouble(ORDER_SL,sl)&&OrderGetDouble(ORDER_TP,tp);
      if(!ok||identity<0||magic<0||type<0||state<0||!TrdNativeText(symbol)||volume<0||price<0||sl<0||tp<0||
         TrdNativeDouble(volume)==""||TrdNativeDouble(price)==""||TrdNativeDouble(sl)==""||TrdNativeDouble(tp)=="") return TrdNativeFail("NATIVE_ORDER_READ_FAILED");
      if(i>0) json+=",";
      json+="{\"ticket\":"+TrdQuote(IntegerToString((long)ticket))+",\"position_identifier\":"+TrdQuote(IntegerToString(identity))+
         ",\"magic\":"+TrdQuote(IntegerToString(magic))+",\"symbol\":"+TrdQuote(symbol)+",\"type\":"+TrdQuote(IntegerToString(type))+
         ",\"state\":"+TrdQuote(IntegerToString(state))+",\"volume\":"+TrdNativeDouble(volume)+",\"price\":"+TrdNativeDouble(price)+
         ",\"sl\":"+TrdNativeDouble(sl)+",\"tp\":"+TrdNativeDouble(tp)+"}";
   }
   json+="]";return (history?HistoryOrdersTotal():OrdersTotal())==count?true:TrdNativeFail("NATIVE_PORTFOLIO_CHANGED");
}
bool TrdNativeDeals(string &json)
{
   int count=HistoryDealsTotal();if(count<0||count>128) return TrdNativeFail("NATIVE_HISTORY_CAPACITY");
   json="[";
   for(int i=0;i<count;i++)
   {
      ulong ticket=HistoryDealGetTicket(i);long order,identity,magic,type,entry,time;
      double volume,price,profit,commission,swap,fee;string symbol;
      if(ticket==0||ticket>(ulong)9223372036854775807||StringFind(json,"\"ticket\":"+TrdQuote(IntegerToString((long)ticket))+",")>=0||
         !HistoryDealGetInteger(ticket,DEAL_ORDER,order)||!HistoryDealGetInteger(ticket,DEAL_POSITION_ID,identity)||
         !HistoryDealGetInteger(ticket,DEAL_MAGIC,magic)||!HistoryDealGetInteger(ticket,DEAL_TYPE,type)||
         !HistoryDealGetInteger(ticket,DEAL_ENTRY,entry)||!HistoryDealGetInteger(ticket,DEAL_TIME_MSC,time)||
         !HistoryDealGetString(ticket,DEAL_SYMBOL,symbol)||!HistoryDealGetDouble(ticket,DEAL_VOLUME,volume)||
         !HistoryDealGetDouble(ticket,DEAL_PRICE,price)||!HistoryDealGetDouble(ticket,DEAL_PROFIT,profit)||
         !HistoryDealGetDouble(ticket,DEAL_COMMISSION,commission)||!HistoryDealGetDouble(ticket,DEAL_SWAP,swap)||
         !HistoryDealGetDouble(ticket,DEAL_FEE,fee)||order<0||identity<0||magic<0||type<0||entry<0||time<1||
         !TrdNativeText(symbol,true)||volume<0||price<0||TrdNativeDouble(volume)==""||TrdNativeDouble(price)==""||
         TrdNativeDouble(profit)==""||TrdNativeDouble(commission)==""||TrdNativeDouble(swap)==""||TrdNativeDouble(fee)=="") return TrdNativeFail("NATIVE_HISTORY_READ_FAILED");
      if(i>0) json+=",";
      json+="{\"ticket\":"+TrdQuote(IntegerToString((long)ticket))+",\"order\":"+TrdQuote(IntegerToString(order))+
         ",\"position_identifier\":"+TrdQuote(IntegerToString(identity))+",\"magic\":"+TrdQuote(IntegerToString(magic))+
         ",\"symbol\":"+TrdQuote(symbol)+",\"type\":"+TrdQuote(IntegerToString(type))+",\"entry\":"+TrdQuote(IntegerToString(entry))+
         ",\"server_time_msc\":"+TrdQuote(IntegerToString(time))+",\"volume\":"+TrdNativeDouble(volume)+",\"price\":"+TrdNativeDouble(price)+
         ",\"profit\":"+TrdNativeDouble(profit)+",\"commission\":"+TrdNativeDouble(commission)+",\"swap\":"+TrdNativeDouble(swap)+",\"fee\":"+TrdNativeDouble(fee)+"}";
   }
   json+="]";return HistoryDealsTotal()==count?true:TrdNativeFail("NATIVE_HISTORY_CHANGED");
}
bool TrdNativeCapture(string &snapshot)
{
   snapshot="";trd_native_snapshot="";
   if(trd_native_fault!="") return false;
   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) return TrdNativeFail("NATIVE_DISCONNECTED");
   if(!TrdNativeIdentity()) return false;
   ulong started=GetTickCount64();long server_time=(long)TimeTradeServer();
   if(server_time<=NativeHistorySeconds||MathAbs((double)(server_time-(long)TimeCurrent()))>30) return TrdNativeFail("NATIVE_SERVER_CLOCK_STALE");
   ResetLastError();
   string currency=AccountInfoString(ACCOUNT_CURRENCY);long mode=AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   double balance=AccountInfoDouble(ACCOUNT_BALANCE),equity=AccountInfoDouble(ACCOUNT_EQUITY),free_margin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   bool permission=AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)&&AccountInfoInteger(ACCOUNT_TRADE_EXPERT)&&
      TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)&&MQLInfoInteger(MQL_TRADE_ALLOWED);
   if(GetLastError()!=0||!TrdNativeText(currency)||mode<0||TrdNativeDouble(balance)==""||TrdNativeDouble(equity)==""||TrdNativeDouble(free_margin)=="") return TrdNativeFail("NATIVE_ACCOUNT_READ_FAILED");
   MqlTick tick={};double point,tick_size,min_volume,step,max_volume,contract;
   long digits,stops,freeze,filling,trade_mode,calc_mode;string base,profit,margin;
   if(!SymbolInfoTick(NativeSymbol,tick)||!SymbolInfoDouble(NativeSymbol,SYMBOL_POINT,point)||
      !SymbolInfoDouble(NativeSymbol,SYMBOL_TRADE_TICK_SIZE,tick_size)||!SymbolInfoDouble(NativeSymbol,SYMBOL_VOLUME_MIN,min_volume)||
      !SymbolInfoDouble(NativeSymbol,SYMBOL_VOLUME_STEP,step)||!SymbolInfoDouble(NativeSymbol,SYMBOL_VOLUME_MAX,max_volume)||
      !SymbolInfoDouble(NativeSymbol,SYMBOL_TRADE_CONTRACT_SIZE,contract)||!SymbolInfoInteger(NativeSymbol,SYMBOL_DIGITS,digits)||
      !SymbolInfoInteger(NativeSymbol,SYMBOL_TRADE_STOPS_LEVEL,stops)||!SymbolInfoInteger(NativeSymbol,SYMBOL_TRADE_FREEZE_LEVEL,freeze)||
      !SymbolInfoInteger(NativeSymbol,SYMBOL_FILLING_MODE,filling)||!SymbolInfoInteger(NativeSymbol,SYMBOL_TRADE_MODE,trade_mode)||
      !SymbolInfoInteger(NativeSymbol,SYMBOL_TRADE_CALC_MODE,calc_mode)||!SymbolInfoString(NativeSymbol,SYMBOL_CURRENCY_BASE,base)||
      !SymbolInfoString(NativeSymbol,SYMBOL_CURRENCY_PROFIT,profit)||!SymbolInfoString(NativeSymbol,SYMBOL_CURRENCY_MARGIN,margin)) return TrdNativeFail("NATIVE_SYMBOL_READ_FAILED");
   // A tick may arrive after the initial clock read. Compare on the same native
   // server-time axis after metadata collection instead of treating it as future.
   server_time=(long)TimeTradeServer();
   if(tick.time_msc<1||tick.time!=(datetime)(tick.time_msc/1000)||tick.time>(datetime)server_time||server_time-(long)tick.time>10||
      tick.bid<=0||tick.ask<tick.bid||point<=0||tick_size<=0||min_volume<=0||step<=0||max_volume<min_volume||contract<=0||
      digits<0||digits>16||stops<0||freeze<0||filling<0||trade_mode<0||calc_mode<0||
      !TrdNativeText(base,true)||!TrdNativeText(profit)||!TrdNativeText(margin)||TrdNativeDouble(tick.bid)==""||TrdNativeDouble(tick.ask)==""||
      TrdNativeDouble(point)==""||TrdNativeDouble(tick_size)==""||TrdNativeDouble(min_volume)==""||TrdNativeDouble(step)==""||
      TrdNativeDouble(max_volume)==""||TrdNativeDouble(contract)=="") return TrdNativeFail("NATIVE_SYMBOL_INVALID_OR_STALE");
   string positions,orders,deals,history_orders,check_positions,check_orders;
   if(!TrdNativePositions(positions)||!TrdNativeOrders(orders)) return false;
   if(!HistorySelect((datetime)(server_time-NativeHistorySeconds),(datetime)server_time)) return TrdNativeFail("NATIVE_HISTORY_UNAVAILABLE");
   if(!TrdNativeDeals(deals)||!TrdNativeOrders(history_orders,true)||!TrdNativePositions(check_positions)||!TrdNativeOrders(check_orders)) return false;
   if(!TrdNativeIdentity()) return false;
   if(positions!=check_positions||orders!=check_orders||!TerminalInfoInteger(TERMINAL_CONNECTED)||
      AccountInfoString(ACCOUNT_CURRENCY)!=currency||AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=mode||GetTickCount64()-started>2000)
      return TrdNativeFail("NATIVE_OBSERVATION_CHANGED");
   snapshot="{\"scope\":\"native-readonly\",\"execution_authority\":false,\"send_enabled\":false,\"observed_at\":"+TrdQuote(TrdNativeStamp((long)TimeGMT()))+
      ",\"server_time\":"+TrdQuote(IntegerToString(server_time))+",\"history_from_server\":"+TrdQuote(IntegerToString(server_time-NativeHistorySeconds))+
      ",\"history_window_observed\":true,\"full_reconciliation\":false,\"account\":{\"login\":"+TrdQuote(NativeExpectedLogin)+
      ",\"server\":"+TrdQuote(NativeExpectedServer)+",\"mode\":\"demo\",\"currency\":"+TrdQuote(currency)+",\"margin_mode\":"+TrdQuote(IntegerToString(mode))+
      ",\"balance\":"+TrdNativeDouble(balance)+",\"equity\":"+TrdNativeDouble(equity)+",\"free_margin\":"+TrdNativeDouble(free_margin)+",\"trade_permission_observed\":"+(permission?"true":"false")+"}"+
      ",\"market\":{\"symbol\":"+TrdQuote(NativeSymbol)+",\"tick_server_time_msc\":"+TrdQuote(IntegerToString(tick.time_msc))+
      ",\"bid\":"+TrdNativeDouble(tick.bid)+",\"ask\":"+TrdNativeDouble(tick.ask)+",\"point\":"+TrdNativeDouble(point)+",\"tick_size\":"+TrdNativeDouble(tick_size)+
      ",\"volume_min\":"+TrdNativeDouble(min_volume)+",\"volume_step\":"+TrdNativeDouble(step)+",\"volume_max\":"+TrdNativeDouble(max_volume)+",\"contract_size\":"+TrdNativeDouble(contract)+
      ",\"digits\":"+TrdQuote(IntegerToString(digits))+",\"stops\":"+TrdQuote(IntegerToString(stops))+",\"freeze\":"+TrdQuote(IntegerToString(freeze))+
      ",\"filling_flags\":"+TrdQuote(IntegerToString(filling))+",\"trade_mode\":"+TrdQuote(IntegerToString(trade_mode))+",\"calc_mode\":"+TrdQuote(IntegerToString(calc_mode))+
      ",\"base_currency\":"+TrdQuote(base)+",\"profit_currency\":"+TrdQuote(profit)+",\"margin_currency\":"+TrdQuote(margin)+"}"+
      ",\"positions\":"+positions+",\"orders\":"+orders+",\"deals\":"+deals+",\"history_orders\":"+history_orders+"}";
   TrdJson verify;if(!verify.Parse(snapshot)) { snapshot="";return TrdNativeFail("NATIVE_OBSERVATION_CAPACITY_OR_ENCODING"); }
   return true;
}

// No native send symbol exists in the build. Permission flags, inputs and profile
// changes cannot bypass this function; there is no demo/live activation option.
bool TrdNativeSend(const MqlTradeRequest &request,MqlTradeResult &result)
{
   MqlTradeResult disabled={};disabled.retcode=TRADE_RETCODE_CLIENT_DISABLES_AT;
   disabled.comment="Invio broker disabilitato nel build locale.";result=disabled;
   trd_native_status="BROKER_SEND_DISABLED";return false;
}
void TrdNativeBuffer(const MqlTradeTransaction &transaction,const MqlTradeResult &result)
{
   if(!ActivateNativeReadOnly||trd_native_fault!="") return;
   if(trd_native_hint_count>=128) { TrdNativeFail("NATIVE_TRANSACTION_OVERFLOW",true);return; }
   int index=trd_native_hint_count++;
   // For REQUEST only trans.type is defined; its other fields are not evidence.
   MqlTradeTransaction request_hint={};request_hint.type=transaction.type;
   trd_native_hints[index].transaction=transaction;
   if(transaction.type==TRADE_TRANSACTION_REQUEST) trd_native_hints[index].transaction=request_hint;
   trd_native_hints[index].observed_at=(long)TimeGMT();
   // request/result parameters are undefined for other transaction types.
   MqlTradeResult blank={};trd_native_hints[index].result=blank;
   if(transaction.type==TRADE_TRANSACTION_REQUEST) trd_native_hints[index].result=result;
}
string TrdNativeHints()
{
   string json="[";
   for(int i=0;i<trd_native_hint_count;i++)
   {
      TrdNativeHint hint=trd_native_hints[i];
      if((long)hint.transaction.type<0||hint.transaction.volume<0||hint.transaction.price<0||!TrdNativeText(hint.transaction.symbol,true)||hint.transaction.deal>(ulong)9223372036854775807||
         hint.transaction.order>(ulong)9223372036854775807||hint.transaction.position>(ulong)9223372036854775807||
         TrdNativeDouble(hint.transaction.volume)==""||TrdNativeDouble(hint.transaction.price)=="") return "";
      if(i>0) json+=",";
      json+="{\"type\":"+TrdQuote(IntegerToString((long)hint.transaction.type))+",\"symbol\":"+TrdQuote(hint.transaction.symbol)+
         ",\"deal\":"+TrdQuote(IntegerToString((long)hint.transaction.deal))+",\"order\":"+TrdQuote(IntegerToString((long)hint.transaction.order))+
         ",\"position_ticket\":"+TrdQuote(IntegerToString((long)hint.transaction.position))+",\"volume\":"+TrdNativeDouble(hint.transaction.volume)+
         ",\"price\":"+TrdNativeDouble(hint.transaction.price)+",\"observed_at\":"+TrdQuote(TrdNativeStamp(hint.observed_at))+
         ",\"request_id\":"+TrdQuote(IntegerToString(hint.result.request_id))+",\"retcode\":"+TrdQuote(IntegerToString(hint.result.retcode))+
         ",\"retcode_external\":"+TrdQuote(IntegerToString(hint.result.retcode_external))+"}";
   }
   return json+"]";
}
bool TrdNativeRecord(const string record)
{
   if(trd_native_sequence>=10000||StringLen(record)>65400||FileSize(trd_native_file)+StringLen(record)+67>8388608) return TrdNativeFail("NATIVE_JOURNAL_CAPACITY",true);
   string digest=TrdHash(trd_native_chain+"\n"+record),line=digest+" "+record+"\r\n";
   ResetLastError();
   if(!FileSeek(trd_native_file,0,SEEK_END)||FileWriteString(trd_native_file,line)!=(uint)StringLen(line)) return TrdNativeFail("NATIVE_JOURNAL_WRITE_FAILED",true);
   FileFlush(trd_native_file);if(GetLastError()!=0) return TrdNativeFail("NATIVE_JOURNAL_FLUSH_FAILED",true);
   trd_native_chain=digest;return true;
}
bool TrdNativeJournal()
{
   trd_native_binding=TrdHash("TRD-NATIVE-READONLY-V1|"+NativeJournal+"|"+NativeExpectedServer+"|"+NativeExpectedLogin+"|"+NativeSymbol+"|"+IntegerToString(NativeHistorySeconds));
   string account_directory=TrdHash("native-readonly|"+NativeExpectedServer+"|"+NativeExpectedLogin);
   trd_native_file=FileOpen("TRD-NATIVE\\"+account_directory+"\\observations.log",FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON,0,CP_UTF8);
   if(trd_native_file==INVALID_HANDLE) return TrdNativeFail("NATIVE_ACCOUNT_OWNED_OR_DISK_FAILED",true);
   if(FileSize(trd_native_file)>8388608) return TrdNativeFail("NATIVE_JOURNAL_CAPACITY",true);
   while(!FileIsEnding(trd_native_file))
   {
      string line=FileReadString(trd_native_file),record=StringSubstr(line,65);TrdJson doc;
      if(StringLen(line)<67||StringSubstr(line,64,1)!=" "||StringSubstr(line,0,64)!=TrdHash(trd_native_chain+"\n"+record)||!doc.Parse(record)) return TrdNativeFail("NATIVE_JOURNAL_CORRUPT",true);
      if(trd_native_chain=="")
      {
         if(!doc.Fields("|type|binding|")||doc.Get("type")!="BIND"||doc.Get("binding")!=trd_native_binding) return TrdNativeFail("NATIVE_JOURNAL_REBOUND",true);
      }
      else
      {
         long sequence;
         if(!doc.Fields("|type|sequence|snapshot|transactions|")||doc.Get("type")!="OBSERVATION"||
            !TrdUnsigned(doc.Get("sequence"),sequence)||sequence!=trd_native_sequence+1||sequence>10000) return TrdNativeFail("NATIVE_JOURNAL_CORRUPT",true);
         trd_native_sequence=sequence;
      }
      trd_native_chain=StringSubstr(line,0,64);
   }
   if(trd_native_chain=="") return TrdNativeRecord("{\"type\":\"BIND\",\"binding\":"+TrdQuote(trd_native_binding)+"}");
   return true;
}
#endif
