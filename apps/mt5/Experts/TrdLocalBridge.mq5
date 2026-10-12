#property strict
#property version "0.10"
#property description "TRD laboratorio locale: conto sintetico, nessun ordine broker"
input bool ActivateLocalSimulation=false;
input string LocalConfig="TRD-LAB\\config.json";
input string LocalCrashPoint=""; // Only synthetic failure testing; never a trading mode.

#include "../Include/TrdLab.mqh"

string TrdHeader(const string headers,const string wanted,bool &valid)
{
   int cursor=0,occurrences=0;string result="";
   while(cursor<StringLen(headers))
   {
      int finish=StringFind(headers,"\n",cursor);if(finish<0) finish=StringLen(headers);
      string line=StringSubstr(headers,cursor,finish-cursor);StringTrimLeft(line);StringTrimRight(line);
      cursor=finish+1;int colon=StringFind(line,":");if(colon<0) continue;
      string name=StringSubstr(line,0,colon);StringToLower(name);
      if(name=="location"||name=="content-encoding") valid=false;
      if(name==wanted)
      {
         result=StringSubstr(line,colon+1);StringTrimLeft(result);StringTrimRight(result);occurrences++;
      }
   }
   if(occurrences!=1) valid=false;
   return result;
}
bool TrdRequest(const string path,const string body,string &reply)
{
   if(trd_sequence==9223372036854775807||StringLen(body)>65536) return TrdStop("TRANSPORT_LIMIT");
   long sequence=trd_sequence+1,now=(long)TimeGMT();
   if(!TrdPersist("{\"type\":\"SEQUENCE\",\"sequence\":"+TrdQuote(IntegerToString(sequence))+"}")) return false;
   string issued=IntegerToString(now),expires=IntegerToString(now+10),seq=IntegerToString(sequence),hex=TrdAsciiHex(body);
   string frame=TrdFrame(trd_env,trd_bridge,trd_instance,trd_key,trd_journal,seq,issued,expires,path,0,"REQUEST",hex);
   if(frame=="") return TrdStop("REQUEST_CONTEXT_INVALID");
   string headers="Content-Type: application/json\r\nX-TRD-Environment: "+trd_env+"\r\nX-TRD-Bridge: "+trd_bridge+
      "\r\nX-TRD-Instance: "+trd_instance+"\r\nX-TRD-Key: "+trd_key+"\r\nX-TRD-Journal: "+trd_journal+
      "\r\nX-TRD-Sequence: "+seq+"\r\nX-TRD-Issued: "+issued+"\r\nX-TRD-Expires: "+expires+
      "\r\nX-TRD-Signature: "+TrdHmac(trd_request_secret,TrdAsciiHex(frame))+"\r\n";
   char data[],result[];
   ArrayResize(data,StringLen(body));for(int i=0;i<StringLen(body);i++) data[i]=(char)StringGetCharacter(body,i);
   string response_headers;int status=WebRequest("POST",trd_origin+path,headers,1000,data,result,response_headers);
   if(status==-1) { trd_last_status="CONTACT_UNAVAILABLE";return false; }
   if(ArraySize(result)<1||ArraySize(result)>65536) return TrdStop("RESPONSE_SIZE_INVALID");
   string response_hex="";for(int i=0;i<ArraySize(result);i++) response_hex+=TrdHexByte((uchar)result[i]);
   bool valid=true;
   if(TrdHeader(response_headers,"content-type",valid)!="application/json") valid=false;
   if(TrdHeader(response_headers,"x-trd-environment",valid)!=trd_env||TrdHeader(response_headers,"x-trd-bridge",valid)!=trd_bridge||
      TrdHeader(response_headers,"x-trd-instance",valid)!=trd_instance||TrdHeader(response_headers,"x-trd-key",valid)!=trd_key||
      TrdHeader(response_headers,"x-trd-journal",valid)!=trd_journal||TrdHeader(response_headers,"x-trd-sequence",valid)!=seq) valid=false;
   string start=TrdHeader(response_headers,"x-trd-issued",valid),finish=TrdHeader(response_headers,"x-trd-expires",valid),signature=TrdHeader(response_headers,"x-trd-signature",valid);
   frame=TrdFrame(trd_env,trd_bridge,trd_instance,trd_key,trd_journal,seq,start,finish,path,status,"RESPONSE",response_hex);
   long begin,end;
   if(!valid||frame==""||!TrdUnsigned(start,begin)||!TrdUnsigned(finish,end)||(long)TimeGMT()<begin||(long)TimeGMT()>=end||
      !TrdEqual(signature,TrdHmac(trd_response_secret,TrdAsciiHex(frame)))) return TrdStop("RESPONSE_AUTHENTICATION_FAILED");
   reply=TrdHexAscii(response_hex);TrdJson doc;
   if(status!=200||!doc.Parse(reply)) return TrdStop("SERVER_REJECTED_REQUEST");
   return true;
}
bool TrdFlushEvents()
{
   string batch="{\"events\":[";int pending=0;
   for(int i=0;i<trd_outbox_count;i++) if(!trd_outbox[i].acknowledged)
   {
      if(pending==100||StringLen(batch)+StringLen(trd_outbox[i].payload)+3>65536) break;
      if(pending>0) batch+=",";batch+=trd_outbox[i].payload;pending++;
   }
   if(pending==0) return true;
   string reply;if(!TrdRequest("/bridge/v1/events",batch+"]}",reply)) return false;
   TrdJson doc;if(!doc.Parse(reply)) return TrdStop("ACK_INVALID");
   int accepted=doc.Field("accepted");if(accepted<0||doc.kind[accepted]!=2) return TrdStop("ACK_INVALID");
   int acknowledged=0;
   for(int node=accepted+1;node<doc.count;node++) if(doc.parent[node]==accepted)
   {
      if(doc.kind[node]!=3) return TrdStop("ACK_INVALID");
      string id=doc.value[node];int index=-1;
      for(int i=0;i<trd_outbox_count;i++) if(trd_outbox[i].id==id) index=i;
      if(index<0||trd_outbox[index].acknowledged||StringFind(batch,trd_outbox[index].payload)<0) return TrdStop("ACK_UNKNOWN_OR_DUPLICATE");
      if(!TrdPersist("{\"type\":\"ACK\",\"id\":"+TrdQuote(id)+"}")) return false;
      acknowledged++;
   }
   if(acknowledged!=pending) { trd_last_status="EVENT_BACKLOG";return false; }
   for(int i=0;i<trd_outbox_count;i++) if(!trd_outbox[i].acknowledged) { trd_last_status="EVENT_BACKLOG";return false; }
   return true;
}
string TrdSnapshot()
{
   string positions="[";int active=0;
   for(int i=0;i<trd_position_count;i++) if(!trd_positions[i].closed)
   {
      if(active++>0) positions+=",";
      positions+="{\"broker_identifier\":"+TrdQuote(trd_positions[i].identifier)+",\"command_id\":"+TrdQuote(trd_positions[i].opening)+
         ",\"symbol\":\"EURUSD.paper\",\"side\":"+TrdQuote(trd_positions[i].side)+",\"volume\":"+TrdQuote(TrdMoney(trd_positions[i].volume))+
         ",\"entry_price\":"+TrdQuote(TrdMoney(trd_positions[i].entry))+",\"stop_loss\":"+TrdQuote(TrdMoney(trd_positions[i].sl))+
         ",\"take_profit\":"+TrdQuote(TrdMoney(trd_positions[i].tp))+"}";
   }
   positions+="]";string snapshot=trd_snapshot_template;
   StringReplace(snapshot,"$NOW$",TrdStamp(trd_snapshot_second));StringReplace(snapshot,"$UUID$",TrdUuid(trd_journal+IntegerToString(trd_sequence+1)));
   TrdJson doc;
   if(!doc.Parse(snapshot)) return "";
   snapshot=doc.Replace("positions",positions);if(!doc.Parse(snapshot)) return "";
   snapshot=doc.Replace("equity",TrdQuote(TrdMoney(1000000000+trd_pnl)));if(!doc.Parse(snapshot)) return "";
   return doc.Replace("free_margin",TrdQuote(TrdMoney(1000000000+trd_pnl)));
}
bool TrdLoadConfig()
{
   int file=FileOpen(LocalConfig,FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(file==INVALID_HANDLE) return false;
   string raw=FileReadString(file);bool complete=FileIsEnding(file);FileClose(file);
   TrdJson config,account,snapshot,instrument;
   if(!complete||!config.Parse(raw)||!config.Fields("|schema|utc_day|origin|environment|bridge|instance|key|journal|account_id|account|profile_hash|request_key_hex|response_key_hex|snapshot_template|")) return false;
   trd_lab_day=config.Get("utc_day");if(trd_lab_day!=TrdToday()) return false;
   trd_env=config.Get("environment");trd_bridge=config.Get("bridge");trd_instance=config.Get("instance");trd_key=config.Get("key");trd_journal=config.Get("journal");
   trd_account_id=config.Get("account_id");trd_account=config.Raw(config.Field("account"));trd_profile=config.Get("profile_hash");
   trd_origin=config.Get("origin");trd_request_secret=config.Get("request_key_hex");trd_response_secret=config.Get("response_key_hex");
   trd_snapshot_template=config.Raw(config.Field("snapshot_template"));
   long port;
   bool local_env=trd_env=="test"||trd_env=="development"||
      (StringLen(trd_env)==17&&StringSubstr(trd_env,0,9)=="test-mt5-"&&TrdHex(StringSubstr(trd_env,9)));
   if(config.Get("schema")!="1"||StringSubstr(trd_origin,0,17)!="http://127.0.0.1:"||
      !TrdUnsigned(StringSubstr(trd_origin,17),port)||port<1||port>65535||
      !local_env||!TrdToken(trd_bridge)||!TrdToken(trd_instance)||!TrdToken(trd_key)||!TrdUuidValid(trd_journal)||
      !TrdUuidValid(trd_account_id)||StringLen(trd_profile)!=64||!TrdHex(trd_profile)||
      StringLen(trd_request_secret)!=64||StringLen(trd_response_secret)!=64||!TrdHex(trd_request_secret)||!TrdHex(trd_response_secret)||trd_request_secret==trd_response_secret||
      !account.Parse(trd_account)||!account.Fields("|environment_id|broker_server|login|mode|")||account.Get("environment_id")!=trd_env||
      account.Get("broker_server")!="TRD-PAPER-SIMULATOR"||account.Get("login")!="1"||account.Get("mode")!="paper"||!snapshot.Parse(trd_snapshot_template)) return false;
   if(snapshot.Raw(snapshot.Field("account"))!=trd_account||snapshot.Get("currency")!="USD"||snapshot.Get("position_mode")!="hedging"||
      snapshot.Get("history_complete")!="true"||snapshot.Get("portfolio_complete")!="true"||snapshot.Raw(snapshot.Field("positions"))!="[]"||
      snapshot.Get("opening_equity")!="10000"||snapshot.Get("equity")!="10000"||snapshot.Get("free_margin")!="10000"||snapshot.Get("net_cash_flow")!="0") return false;
   int quotes=snapshot.Field("quotes"),instruments=snapshot.Field("instruments");
   if(quotes<0||instruments<0||snapshot.kind[quotes]!=2||snapshot.kind[instruments]!=2) return false;
   int quote=-1,metadata=-1;
   for(int i=1;i<snapshot.count;i++)
   {
      if(snapshot.parent[i]==quotes) { if(quote>=0) return false;quote=i; }
      if(snapshot.parent[i]==instruments) { if(metadata>=0) return false;metadata=i; }
   }
   if(quote<0||metadata<0||snapshot.Get("symbol",quote)!="EURUSD.paper"||snapshot.Get("market_open",quote)!="true"||
      !TrdDecimal(snapshot.Get("bid",quote),trd_bid)||!TrdDecimal(snapshot.Get("ask",quote),trd_ask)||
      trd_bid<50000||trd_ask>200000||trd_bid>=trd_ask||trd_ask-trd_bid>30||!instrument.Parse(snapshot.Raw(metadata))) return false;
   return instrument.Get("symbol")=="EURUSD.paper"&&instrument.Get("base_currency")=="EUR"&&instrument.Get("quote_currency")=="USD"&&
      instrument.Get("margin_currency")=="EUR"&&instrument.Get("profile")=="spot-fx-v1"&&instrument.Get("contract_size")=="100000"&&
      instrument.Get("point")=="0.00001"&&instrument.Get("tick_size")=="0.00001"&&instrument.Get("volume_min")=="0.01"&&instrument.Get("volume_step")=="0.01"&&
      instrument.Get("stops_level_points")=="10"&&instrument.Get("freeze_level_points")=="5"&&instrument.Get("margin_rate")=="1"&&
      instrument.Get("commission_per_lot_account")=="7"&&instrument.Get("slippage_buffer_points")=="5"&&instrument.Get("attached_stops_supported")=="true";
}
int OnInit()
{
   if(!ActivateLocalSimulation) { trd_last_status="DISABLED";return INIT_SUCCEEDED; }
   if(MQLInfoInteger(MQL_TESTER)||!TrdSelfTest()||!TrdLoadConfig()) { TrdStop("LOCAL_CONFIG_OR_SELF_TEST_FAILED");return INIT_FAILED; }
   string directory="TRD-LAB\\"+TrdHash(trd_env+"|TRD-PAPER-SIMULATOR|1");
   // FILE_COMMON plus no SHARE flags provides an account-wide lock across terminals.
   trd_journal_file=FileOpen(directory+"\\journal.log",FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON,0,CP_UTF8);
   if(trd_journal_file==INVALID_HANDLE) { TrdStop("ACCOUNT_ALREADY_OWNED_OR_DISK_FAILED");return INIT_FAILED; }
   trd_broker_file=FileOpen(directory+"\\synthetic-broker.log",FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON,0,CP_UTF8);
   if(trd_broker_file==INVALID_HANDLE) { TrdStop("BROKER_LEDGER_UNAVAILABLE");return INIT_FAILED; }
   bool journal_empty=FileSize(trd_journal_file)==0,broker_empty=FileSize(trd_broker_file)==0;
   if(journal_empty!=broker_empty) { TrdStop("INCOMPLETE_DURABLE_PAIR");return INIT_FAILED; }
   if(!TrdReplay(trd_journal_file,false,trd_journal_chain)||!TrdReplay(trd_broker_file,true,trd_broker_chain)) { TrdStop("JOURNAL_CORRUPT_OR_REBOUND");return INIT_FAILED; }
   if(journal_empty)
   {
      if(!TrdPersist("{\"type\":\"BIND\",\"binding\":"+TrdQuote(TrdHash(trd_profile+trd_origin+trd_journal+TrdHash(trd_request_secret)+TrdHash(trd_response_secret)))+"}")||
         !TrdRecord(trd_broker_file,trd_broker_chain,"{\"type\":\"BIND\",\"binding\":"+TrdQuote(TrdHash(trd_profile+trd_origin+trd_journal))+"}")) return INIT_FAILED;
   }
   for(int i=0;i<trd_ledger_count;i++)
   {
      int command=TrdCommandIndex(trd_ledger[i].id);
      if(command<0||trd_commands[command].hash!=trd_ledger[i].hash||trd_commands[command].state=="RECEIVED"||trd_commands[command].state=="REJECTED")
      { TrdStop("LEDGER_WITHOUT_DURABLE_INTENT");return INIT_FAILED; }
   }
   for(int i=0;i<trd_command_count;i++) if(trd_commands[i].state=="COMPLETE"&&TrdResultIndex(trd_commands[i].id)<0)
   { TrdStop("COMPLETED_WITHOUT_ECONOMIC_EVIDENCE");return INIT_FAILED; }
   if(!TrdRecover()||!EventSetTimer(2)) { TrdStop("RECOVERY_OR_TIMER_FAILED");return INIT_FAILED; }
   trd_last_status="RECONCILING";return INIT_SUCCEEDED;
}
void OnTimer()
{
   if(!ActivateLocalSimulation||trd_fault!="") return;
   if(TrdToday()!=trd_lab_day) { TrdStop("LAB_SESSION_DAY_EXPIRED");return; }
   if(!TrdRecover()||!TrdFlushEvents()) return;
   // TimeGMT has second resolution. Do not fabricate a newer observation when a
   // restart or fast handler runs within the previously persisted snapshot second.
   long observed=(long)TimeGMT();
   if(StringSubstr(TrdStamp(observed),0,10)!=trd_lab_day) { TrdStop("LAB_SESSION_DAY_EXPIRED");return; }
   if(observed<=trd_snapshot_second) { trd_last_status="CLOCK_WAIT";return; }
   if(!TrdPersist("{\"type\":\"CLOCK\",\"second\":"+TrdQuote(IntegerToString(observed))+"}")) return;
   string snapshot=TrdSnapshot(),reply;
   if(snapshot=="") { TrdStop("SNAPSHOT_INVALID");return; }
   if(!TrdRequest("/bridge/v1/snapshot",snapshot,reply)||!TrdRequest("/bridge/v1/poll","{}",reply)) return;
   TrdJson doc;if(!doc.Parse(reply)) { TrdStop("POLL_INVALID");return; }
   trd_last_status=doc.Get("status");int command=doc.Field("command");
   if(command<0||doc.kind[command]==5) return;
   long epoch;
   if(doc.kind[command]!=3||!TrdUnsigned(doc.Get("safety_epoch"),epoch)||epoch<1) { TrdStop("POLL_AUTHORITY_INVALID");return; }
   trd_epoch=epoch;string payload=TrdHexAscii(TrdBase64(doc.Get("command")));
   if(TrdAccept(payload,doc.Get("command_hash"))) TrdFlushEvents();
}
void OnTradeTransaction(const MqlTradeTransaction &transaction,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   // This build observes only its independent synthetic ledger. Terminal trades
   // cannot become authenticated laboratory fills, and there are no network calls here.
}
void OnDeinit(const int reason)
{
   EventKillTimer();if(trd_broker_file!=INVALID_HANDLE) FileClose(trd_broker_file);
   if(trd_journal_file!=INVALID_HANDLE) FileClose(trd_journal_file);
}
