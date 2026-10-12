// Exact synthetic EURUSD/USD executor. Deliberately contains no broker submission.
#ifndef TRD_LAB_MQH
#define TRD_LAB_MQH
#include "TrdCore.mqh"

struct TrdCommandState { string id,hash,payload,state; };
struct TrdLedgerRow { string id,hash,payload,outcome; };
struct TrdOutboxRow { string id,payload;bool acknowledged; };
struct TrdLabPosition { string identifier,opening,side;long volume,entry,sl,tp,revision;bool closed; };

string trd_env,trd_bridge,trd_instance,trd_key,trd_journal,trd_account,trd_account_id,trd_profile,trd_origin;
string trd_request_secret,trd_response_secret,trd_snapshot_template,trd_lab_day,trd_last_status="DISABLED",trd_fault="";
long trd_sequence=0,trd_epoch=0,trd_bid=0,trd_ask=0,trd_pnl=0,trd_snapshot_second=0;
int trd_journal_file=INVALID_HANDLE,trd_broker_file=INVALID_HANDLE;
string trd_journal_chain="",trd_broker_chain="";
TrdCommandState trd_commands[1000];int trd_command_count=0;
TrdLedgerRow trd_ledger[1000];int trd_ledger_count=0;
TrdOutboxRow trd_outbox[4000];int trd_outbox_count=0;
TrdLabPosition trd_positions[1000];int trd_position_count=0;

string TrdStamp(const long second)
{
   string s=TimeToString((datetime)second,TIME_DATE|TIME_SECONDS);
   StringReplace(s,".","-");StringReplace(s," ","T");return s+"+00:00";
}
string TrdNow() { return TrdStamp((long)TimeGMT()); }
string TrdToday()
{
   string day=TimeToString(TimeGMT(),TIME_DATE);StringReplace(day,".","-");return day;
}
long TrdExpiry(const string s)
{
   if(StringLen(s)<20 || StringSubstr(s,10,1)!="T" ||
      (StringSubstr(s,StringLen(s)-1)!="Z" && StringSubstr(s,StringLen(s)-6)!="+00:00")) return 0;
   int suffix=StringSubstr(s,StringLen(s)-1)=="Z"?StringLen(s)-1:StringLen(s)-6;
   if(suffix!=19)
   {
      if(suffix<21||suffix>26||StringSubstr(s,19,1)!=".") return 0;
      for(int i=20;i<suffix;i++) if(StringGetCharacter(s,i)<48||StringGetCharacter(s,i)>57) return 0;
   }
   string text=StringSubstr(s,0,19);StringReplace(text,"-",".");StringReplace(text,"T"," ");
   long result=(long)StringToTime(text);
   return TimeToString((datetime)result,TIME_DATE|TIME_SECONDS)==text?result:0;
}
bool TrdStop(const string reason) { trd_fault=reason;trd_last_status="FAULT";return false; }
int TrdCommandIndex(const string id)
{
   for(int i=0;i<trd_command_count;i++) if(trd_commands[i].id==id) return i;
   return -1;
}
int TrdPositionIndex(const string id)
{
   for(int i=0;i<trd_position_count;i++) if(trd_positions[i].identifier==id) return i;
   return -1;
}
int TrdResultIndex(const string id)
{
   for(int i=0;i<trd_ledger_count;i++) if(trd_ledger[i].id==id) return i;
   return -1;
}
bool TrdRecord(const int handle,string &chain,const string record)
{
   if(StringLen(record)>65536) return TrdStop("JOURNAL_RECORD_TOO_LARGE");
   string digest=TrdHash(chain+"\n"+record),line=digest+" "+record+"\r\n";
   ResetLastError();
   if(!FileSeek(handle,0,SEEK_END)||FileWriteString(handle,line)!=(uint)StringLen(line)) return TrdStop("JOURNAL_WRITE_FAILED");
   FileFlush(handle);
   if(GetLastError()!=0) return TrdStop("JOURNAL_FLUSH_FAILED");
   chain=digest;return true;
}
bool TrdApplyJournal(const string raw)
{
   TrdJson doc;
   if(!doc.Parse(raw)) return false;
   string type=doc.Get("type");
   if(type=="BIND") return trd_sequence==0&&trd_command_count==0&&doc.Get("binding")==TrdHash(trd_profile+trd_origin+trd_journal+TrdHash(trd_request_secret)+TrdHash(trd_response_secret));
   if(type=="SEQUENCE")
   {
      long sequence;if(!TrdUnsigned(doc.Get("sequence"),sequence)||sequence!=trd_sequence+1) return false;
      trd_sequence=sequence;return true;
   }
   if(type=="CLOCK")
   {
      long second;if(!TrdUnsigned(doc.Get("second"),second)||second<=trd_snapshot_second) return false;
      trd_snapshot_second=second;return true;
   }
   if(type=="COMMAND")
   {
      string id=doc.Get("id"),hash=doc.Get("hash"),payload=TrdHexAscii(doc.Get("payload")),state=doc.Get("state");
      int index=TrdCommandIndex(id);
      if(!TrdUuidValid(id)||hash!=TrdHash(payload)) return false;
      if(index<0)
      {
         if(state!="RECEIVED"||trd_command_count>=1000) return false;
         index=trd_command_count++;trd_commands[index].id=id;trd_commands[index].hash=hash;trd_commands[index].payload=payload;
      }
      else if(trd_commands[index].hash!=hash || !(
         (trd_commands[index].state=="RECEIVED"&&(state=="SEND_INTENT"||state=="REJECTED")) ||
         (trd_commands[index].state=="SEND_INTENT"&&(state=="UNKNOWN"||state=="COMPLETE")) ||
         (trd_commands[index].state=="UNKNOWN"&&state=="COMPLETE"))) return false;
      trd_commands[index].state=state;return true;
   }
   if(type=="EVENT")
   {
      string payload=TrdHexAscii(doc.Get("payload"));TrdJson event;
      if(!event.Parse(payload)||!TrdUuidValid(event.Get("event_id"))) return false;
      for(int i=0;i<trd_outbox_count;i++) if(trd_outbox[i].id==event.Get("event_id")) return trd_outbox[i].payload==payload;
      if(trd_outbox_count>=4000) return false;
      trd_outbox[trd_outbox_count].id=event.Get("event_id");trd_outbox[trd_outbox_count].payload=payload;
      trd_outbox[trd_outbox_count++].acknowledged=false;return true;
   }
   if(type=="ACK")
   {
      for(int i=0;i<trd_outbox_count;i++) if(trd_outbox[i].id==doc.Get("id")) { trd_outbox[i].acknowledged=true;return true; }
   }
   return false;
}
bool TrdPersist(const string raw)
{
   if(!TrdRecord(trd_journal_file,trd_journal_chain,raw)) return false;
   return TrdApplyJournal(raw)?true:TrdStop("JOURNAL_STATE_INVALID");
}
bool TrdCommandRecord(const string id,const string hash,const string payload,const string state)
{
   return TrdPersist("{\"type\":\"COMMAND\",\"id\":"+TrdQuote(id)+",\"hash\":"+TrdQuote(hash)+",\"payload\":"+TrdQuote(TrdAsciiHex(payload))+",\"state\":"+TrdQuote(state)+"}");
}
bool TrdEvent(const string payload)
{
   TrdJson event;if(!event.Parse(payload)) return TrdStop("EVENT_INVALID");
   for(int i=0;i<trd_outbox_count;i++) if(trd_outbox[i].id==event.Get("event_id")) return trd_outbox[i].payload==payload;
   return TrdPersist("{\"type\":\"EVENT\",\"payload\":"+TrdQuote(TrdAsciiHex(payload))+"}");
}
string TrdObservation(const string id,const string hash,const string kind,const string extra="")
{
   return "{\"event_id\":"+TrdQuote(TrdUuid(trd_journal+id+kind))+",\"command_id\":"+TrdQuote(id)+",\"command_hash\":"+TrdQuote(hash)+",\"kind\":"+TrdQuote(kind)+",\"observed_at\":"+TrdQuote(TrdNow())+extra+"}";
}
// Persistent broker rows are independent from the executor journal; replay rebuilds
// positions and realized results and refuses contradictory economic state.
bool TrdApplyBroker(const string raw)
{
   TrdJson row,command,event;
   if(!row.Parse(raw)) return false;
   if(row.Get("type")=="BIND") return trd_ledger_count==0&&row.Get("binding")==TrdHash(trd_profile+trd_origin+trd_journal);
   if(!row.Fields("|type|hash|payload|outcome|")||row.Get("type")!="RESULT"||!command.Parse(TrdHexAscii(row.Get("payload")))||!event.Parse(TrdHexAscii(row.Get("outcome")))||trd_ledger_count>=1000) return false;
   string id=command.Get("command_id"),hash=row.Get("hash"),action=command.Get("action");
   if(!TrdUuidValid(id)||!TrdUuidValid(event.Get("event_id"))||TrdResultIndex(id)>=0||TrdHash(command.source)!=hash||event.Get("command_id")!=id||event.Get("command_hash")!=hash) return false;
   long volume,price,sl,tp;
   if(!TrdDecimal(command.Get("volume"),volume)||volume<1000||volume>100000||volume%1000!=0||!TrdDecimal(command.Get("stop_loss"),sl)||sl<=0||!TrdDecimal(command.Get("take_profit"),tp)||tp<=0) return false;
   int position=TrdPositionIndex(event.Get("position_identifier"));
   if(action=="")
   {
      if(position>=0||event.Get("kind")!="FILL"||event.Get("volume")!=command.Get("volume")||
         event.Get("broker_ticket")!=IntegerToString(trd_ledger_count+1)||event.Get("broker_deal_id")!=event.Get("broker_ticket")||
         event.Get("position_identifier")!=event.Get("broker_ticket")||!TrdDecimal(event.Get("price"),price)||price<=0) return false;
      position=trd_position_count++;
      trd_positions[position].identifier=event.Get("position_identifier");trd_positions[position].opening=id;
      trd_positions[position].side=command.Get("side");trd_positions[position].volume=volume;trd_positions[position].entry=price;
      trd_positions[position].sl=sl;trd_positions[position].tp=tp;trd_positions[position].revision=1;trd_positions[position].closed=false;
   }
   else
   {
      if(position<0||trd_positions[position].closed||trd_positions[position].volume!=volume||trd_positions[position].opening!=command.Get("opening_command_id")||
         command.Get("position_identifier")!=event.Get("position_identifier")||event.Get("operation_id")!=IntegerToString(trd_ledger_count+1)||
         command.Get("position_revision")!=IntegerToString(trd_positions[position].revision)) return false;
      if(action=="CLOSE")
      {
         if(event.Get("kind")!="POSITION_CLOSED"||event.Get("volume")!=command.Get("volume")||
            event.Get("broker_deal_id")!=IntegerToString(10000000000000000+trd_ledger_count+1)||!TrdDecimal(event.Get("price"),price)||price<=0) return false;
         trd_pnl+=(price-trd_positions[position].entry)*volume*(trd_positions[position].side=="BUY"?1:-1)-7*volume;
         trd_positions[position].closed=true;
      }
      else if(action=="MODIFY_STOPS"&&event.Get("kind")=="STOPS_CHANGED"&&event.Get("stop_loss")==command.Get("stop_loss")&&event.Get("take_profit")==command.Get("take_profit")) { trd_positions[position].sl=sl;trd_positions[position].tp=tp; }
      else return false;
      trd_positions[position].revision++;
   }
   trd_ledger[trd_ledger_count].id=id;trd_ledger[trd_ledger_count].hash=hash;
   trd_ledger[trd_ledger_count].payload=command.source;trd_ledger[trd_ledger_count++].outcome=event.source;return true;
}
bool TrdReplay(const int handle,const bool broker,string &chain)
{
   chain="";FileSeek(handle,0,SEEK_SET);int records=0;
   while(!FileIsEnding(handle))
   {
      string line=FileReadString(handle);
      if(StringLen(line)<67||StringLen(line)>131200||++records>20000) return false;
      string digest=StringSubstr(line,0,64),raw=StringSubstr(line,65);TrdJson doc;
      if(StringSubstr(line,64,1)!=" "||digest!=TrdHash(chain+"\n"+raw)||!doc.Parse(raw)||
         (records==1 && doc.Get("type")!="BIND")||(records>1 && doc.Get("type")=="BIND")) return false;
      if(broker?!TrdApplyBroker(raw):!TrdApplyJournal(raw)) return false;
      chain=digest;
   }
   return true;
}
bool TrdPreflight(const string payload,long &price)
{
   TrdJson c;
   if(!c.Parse(payload)) return false;
   string action=c.Get("action");
   string common="|command_id|trace_id|account_id|account|bridge_id|instance_id|generation|profile_hash|safety_epoch|symbol|side|volume|stop_loss|take_profit|price_band_low|price_band_high|max_spread_points|max_deviation_points|expires_at|";
   string fields=action==""?common+"approval_id|reservation_id|policy_version|signal_id|signal_version|source_id|source_version|max_risk|":
      common+"action|request_id|position_id|position_revision|opening_command_id|position_identifier|entry_price|entry_value|previous_stop_loss|previous_take_profit|";
   int account=c.Field("account");
   if(!c.Fields(fields)||!c.Fields("|environment_id|broker_server|login|mode|",account)||c.Raw(account)!=trd_account||
      c.Get("account_id")!=trd_account_id||c.Get("bridge_id")!=trd_bridge||c.Get("instance_id")!=trd_instance||c.Get("generation")!="1"||
      c.Get("profile_hash")!=trd_profile||c.Get("safety_epoch")!=IntegerToString(trd_epoch)||c.Get("symbol")!="EURUSD.paper"||
      !TrdUuidValid(c.Get("command_id"))||!TrdUuidValid(c.Get("trace_id"))||TrdExpiry(c.Get("expires_at"))<=(long)TimeGMT()) return false;
   string decimals="|volume|stop_loss|take_profit|price_band_low|price_band_high|max_spread_points|max_deviation_points|max_risk|entry_price|entry_value|previous_stop_loss|previous_take_profit|";
   string integers="|generation|safety_epoch|policy_version|signal_version|source_version|position_revision|";
   for(int i=1;i<c.count;i++) if(c.parent[i]==0)
   {
      if(StringFind(decimals,"|"+c.name[i]+"|")>=0 && c.kind[i]!=3) return false;
      if(StringFind(integers,"|"+c.name[i]+"|")>=0)
      {
         long n;if(c.kind[i]!=6||!TrdUnsigned(c.value[i],n)||n<1) return false;
      }
   }
   string side=c.Get("side");if(side!="BUY"&&side!="SELL") return false;
   long volume,sl,tp,low,high,spread,deviation;
   if(!TrdDecimal(c.Get("volume"),volume)||volume<1000||volume>100000||volume%1000!=0||
      !TrdDecimal(c.Get("stop_loss"),sl)||sl<=0||!TrdDecimal(c.Get("take_profit"),tp)||tp<=0||
      !TrdDecimal(c.Get("price_band_low"),low)||!TrdDecimal(c.Get("price_band_high"),high)||
      !TrdDecimal(c.Get("max_spread_points"),spread)||!TrdDecimal(c.Get("max_deviation_points"),deviation)) return false;
   if(spread>3000000) spread=3000000;if(deviation>2000000) deviation=2000000;
   price=action==""?(side=="BUY"?trd_ask:trd_bid):(side=="BUY"?trd_bid:trd_ask);
   if(low>high||price<low||price>high||high-low>2*(deviation/100000)||(trd_ask-trd_bid)*100000>spread) return false;
   if(action!="CLOSE")
   {
      long distance=side=="BUY"?trd_bid-sl:sl-trd_ask,profit=side=="BUY"?tp-trd_ask:trd_bid-tp;
      if(distance<10||profit<10||distance<=5||profit<=5) return false;
   }
   if(action=="")
   {
      long risk;
      return TrdUuidValid(c.Get("approval_id"))&&TrdUuidValid(c.Get("reservation_id"))&&TrdUuidValid(c.Get("signal_id"))&&TrdUuidValid(c.Get("source_id"))&&TrdDecimal(c.Get("max_risk"),risk)&&
         ((side=="BUY"?price-sl:sl-price)+5)*volume+7*volume<=risk;
   }
   if(action!="CLOSE"&&action!="MODIFY_STOPS") return false;
   int p=TrdPositionIndex(c.Get("position_identifier"));long entry,previous_sl,previous_tp,entry_value;
   if(p<0||trd_positions[p].closed||trd_positions[p].opening!=c.Get("opening_command_id")||trd_positions[p].volume!=volume||trd_positions[p].side!=side||
      c.Get("position_revision")!=IntegerToString(trd_positions[p].revision)||
      !TrdUuidValid(c.Get("request_id"))||!TrdUuidValid(c.Get("position_id"))||
      !TrdDecimal(c.Get("entry_price"),entry)||entry!=trd_positions[p].entry||
      !TrdScaledDecimal(c.Get("entry_value"),entry_value,10)||entry_value!=entry*volume||
      !TrdDecimal(c.Get("previous_stop_loss"),previous_sl)||previous_sl!=trd_positions[p].sl||
      !TrdDecimal(c.Get("previous_take_profit"),previous_tp)||previous_tp!=trd_positions[p].tp) return false;
   return action=="CLOSE"?(sl==previous_sl&&tp==previous_tp):(side=="BUY"?sl>=previous_sl:sl<=previous_sl);
}
bool TrdRecover()
{
   for(int i=0;i<trd_command_count;i++) if(trd_commands[i].state=="SEND_INTENT"||trd_commands[i].state=="UNKNOWN")
   {
      int result=TrdResultIndex(trd_commands[i].id);
      if(result>=0)
      {
         if(trd_ledger[result].hash!=trd_commands[i].hash||!TrdEvent(trd_ledger[result].outcome)||
            !TrdCommandRecord(trd_commands[i].id,trd_commands[i].hash,trd_commands[i].payload,"COMPLETE")) return false;
      }
      else if(trd_commands[i].state!="UNKNOWN")
      {
         if(!TrdEvent(TrdObservation(trd_commands[i].id,trd_commands[i].hash,"UNKNOWN"))||
            !TrdCommandRecord(trd_commands[i].id,trd_commands[i].hash,trd_commands[i].payload,"UNKNOWN")) return false;
      }
   }
   return true;
}
bool TrdAccept(const string payload,const string hash)
{
   TrdJson c;
   if(!c.Parse(payload)||hash!=TrdHash(payload)||!TrdUuidValid(c.Get("command_id"))) return TrdStop("COMMAND_BYTES_INVALID");
   string id=c.Get("command_id");int index=TrdCommandIndex(id);
   if(index>=0) return trd_commands[index].hash==hash?TrdRecover():TrdStop("COMMAND_HASH_CONFLICT");
   if(!TrdCommandRecord(id,hash,payload,"RECEIVED")||!TrdEvent(TrdObservation(id,hash,"RECEIVED"))) return false;
   long price;
   if(!TrdPreflight(payload,price)) return TrdEvent(TrdObservation(id,hash,"REJECTED"))&&TrdCommandRecord(id,hash,payload,"REJECTED");
   if(!TrdCommandRecord(id,hash,payload,"SEND_INTENT")||!TrdEvent(TrdObservation(id,hash,"SEND_INTENT"))) return false;
   // A fault injected after this durable intent never authorizes a second submission.
   if(LocalCrashPoint=="after_intent") return TrdStop("LAB_CRASH_AFTER_INTENT");
   if(TrdExpiry(c.Get("expires_at"))<=(long)TimeGMT()) return TrdRecover();
   long ticket=trd_ledger_count+1;string action=c.Get("action"),kind,extra;
   if(action=="")
   {
      kind="FILL";extra=",\"broker_ticket\":"+TrdQuote(IntegerToString(ticket))+",\"broker_deal_id\":"+TrdQuote(IntegerToString(ticket))+
         ",\"position_identifier\":"+TrdQuote(IntegerToString(ticket))+",\"volume\":"+TrdQuote(c.Get("volume"))+",\"price\":"+TrdQuote(TrdMoney(price));
   }
   else
   {
      kind=action=="CLOSE"?"POSITION_CLOSED":"STOPS_CHANGED";
      extra=",\"operation_id\":"+TrdQuote(IntegerToString(ticket))+",\"position_identifier\":"+TrdQuote(c.Get("position_identifier"));
      extra+=action=="CLOSE"?",\"broker_deal_id\":"+TrdQuote(IntegerToString(10000000000000000+ticket))+",\"volume\":"+TrdQuote(c.Get("volume"))+",\"price\":"+TrdQuote(TrdMoney(price)):
         ",\"stop_loss\":"+TrdQuote(c.Get("stop_loss"))+",\"take_profit\":"+TrdQuote(c.Get("take_profit"));
   }
   string outcome=TrdObservation(id,hash,kind,extra);
   string row="{\"type\":\"RESULT\",\"hash\":"+TrdQuote(hash)+",\"payload\":"+TrdQuote(TrdAsciiHex(payload))+",\"outcome\":"+TrdQuote(TrdAsciiHex(outcome))+"}";
   if(!TrdRecord(trd_broker_file,trd_broker_chain,row)||!TrdApplyBroker(row)) return TrdStop("BROKER_LEDGER_FAILED");
   if(LocalCrashPoint=="after_result") return TrdStop("LAB_CRASH_AFTER_RESULT");
   return TrdRecover();
}
#endif
