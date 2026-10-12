// The only compiled terminal port. Never calls OrderCheck/OrderSend, AccountInfo,
// SymbolInfo or HistorySelect. Native calls require a future accepted demo build.
#ifndef TRD_BROKER_SIMULATION_MQH
#define TRD_BROKER_SIMULATION_MQH

TrdBrokerContext TrdSimulationContext(const string payload)
{
   TrdBrokerContext b;
   b.server="TRD-PAPER-SIMULATOR";b.login="1";b.currency="USD";b.position_mode="hedging";b.symbol="EURUSD.paper";
   b.connected=true;b.trade_allowed=true;b.history_complete=true;b.portfolio_complete=true;b.attached_stops=true;b.fok=true;b.owned=true;
   b.observed_at=(long)TimeGMT();b.bid=trd_bid;b.ask=trd_ask;b.point=1;b.tick=1;b.volume_min=1000;b.volume_step=1000;b.volume_max=100000;b.stops=10;b.freeze=5;
   b.ticket=0;b.identifier=0;b.magic=20261012;b.volume=0;b.entry=0;b.sl=0;b.tp=0;b.revision=0;
   TrdJson c;
   if(c.Parse(payload))
   {
      int i=TrdPositionIndex(c.Get("position_identifier"));
      if(i>=0&&!trd_positions[i].closed)
      {
         TrdUnsigned(trd_positions[i].identifier,b.identifier);b.ticket=b.identifier;
         b.volume=trd_positions[i].volume;b.entry=trd_positions[i].entry;b.sl=trd_positions[i].sl;b.tp=trd_positions[i].tp;
         b.opening=trd_positions[i].opening;b.side=trd_positions[i].side;b.revision=trd_positions[i].revision;
      }
   }
   if(LocalBrokerScenario=="disconnected") b.connected=false;
   if(LocalBrokerScenario=="permissions") b.trade_allowed=false;
   if(LocalBrokerScenario=="stale_quote") b.observed_at-=3;
   if(LocalBrokerScenario=="history_gap") b.history_complete=false;
   if(LocalBrokerScenario=="foreign_position") b.owned=false;
   if(LocalBrokerScenario=="changed_volume") b.volume+=1000;
   return b;
}

bool TrdSimulationCheck(const TrdBrokerPlan &p,MqlTradeCheckResult &result)
{
   result.retcode=0;
   if(LocalBrokerScenario=="check_rejected") { result.retcode=TRADE_RETCODE_NO_MONEY;return true; }
   if(LocalBrokerScenario=="check_false") return false;
   if(LocalBrokerScenario=="quote_changed_after_check") trd_ask++;
   return p.request.magic==20261012&&p.request.symbol=="EURUSD.paper";
}

bool TrdBrokerRecord(const string type,const string hash,const TrdBrokerPlan &p,
   const bool ok,const uint retcode,const int external,const uint request_id,const long order,const long deal,const long volume,const long price)
{
   return TrdPersist("{\"type\":"+TrdQuote(type)+",\"id\":"+TrdQuote(p.command_id)+",\"hash\":"+TrdQuote(hash)+
      ",\"request\":"+TrdQuote(TrdAsciiHex(TrdBrokerRequestJson(p)))+",\"api_ok\":"+(ok?"true":"false")+
      ",\"retcode\":"+TrdQuote(IntegerToString(retcode))+",\"retcode_external\":"+TrdQuote(IntegerToString(external))+
      ",\"request_id\":"+TrdQuote(IntegerToString(request_id))+",\"order\":"+TrdQuote(IntegerToString(order))+
      ",\"deal\":"+TrdQuote(IntegerToString(deal))+",\"volume\":"+TrdQuote(IntegerToString(volume))+
      ",\"price\":"+TrdQuote(IntegerToString(price))+"}");
}

bool TrdSimulationEvidence(const string payload,const string hash,const TrdBrokerPlan &p)
{
   TrdJson c;if(!c.Parse(payload)) return false;
   long ticket=trd_ledger_count+1;string kind,extra;
   if(p.action=="")
   {
      kind="FILL";extra=",\"broker_ticket\":"+TrdQuote(IntegerToString(ticket))+",\"broker_deal_id\":"+TrdQuote(IntegerToString(ticket))+
         ",\"position_identifier\":"+TrdQuote(IntegerToString(ticket))+",\"volume\":"+TrdQuote(c.Get("volume"))+",\"price\":"+TrdQuote(TrdMoney(p.price));
   }
   else
   {
      kind=p.action=="CLOSE"?"POSITION_CLOSED":"STOPS_CHANGED";
      extra=",\"operation_id\":"+TrdQuote(IntegerToString(ticket))+",\"position_identifier\":"+TrdQuote(p.position_identifier);
      extra+=p.action=="CLOSE"?",\"broker_deal_id\":"+TrdQuote(IntegerToString(10000000000000000+ticket))+",\"volume\":"+TrdQuote(c.Get("volume"))+",\"price\":"+TrdQuote(TrdMoney(p.price)):
         ",\"stop_loss\":"+TrdQuote(c.Get("stop_loss"))+",\"take_profit\":"+TrdQuote(c.Get("take_profit"));
   }
   string outcome=TrdObservation(p.command_id,hash,kind,extra);
   string row="{\"type\":\"RESULT\",\"hash\":"+TrdQuote(hash)+",\"payload\":"+TrdQuote(TrdAsciiHex(payload))+",\"outcome\":"+TrdQuote(TrdAsciiHex(outcome))+"}";
   return TrdRecord(trd_broker_file,trd_broker_chain,row)&&TrdApplyBroker(row);
}

bool TrdSimulationSend(const string payload,const string hash,const TrdBrokerPlan &p,MqlTradeResult &result)
{
   result.retcode=TRADE_RETCODE_DONE;result.retcode_external=0;result.request_id=(uint)(trd_command_count);
   result.order=(ulong)(trd_ledger_count+1);result.deal=0;result.volume=0;result.price=0;
   if(LocalBrokerScenario=="send_false") return false;
   if(LocalBrokerScenario=="send_rejected") { result.retcode=TRADE_RETCODE_REJECT;return true; }
   if(LocalBrokerScenario=="external_error") { result.retcode=TRADE_RETCODE_ERROR;result.retcode_external=-7;return true; }
   if(LocalBrokerScenario=="timeout") { result.retcode=TRADE_RETCODE_TIMEOUT;return true; }
   if(LocalBrokerScenario=="connection") { result.retcode=TRADE_RETCODE_CONNECTION;return true; }
   if(LocalBrokerScenario=="placed") { result.retcode=TRADE_RETCODE_PLACED;return true; }
   if(LocalBrokerScenario=="done_without_evidence") return true;
   if(LocalBrokerScenario=="partial")
   {
      // Preserve the original partial reply, but never project a made-up full fill.
      result.retcode=TRADE_RETCODE_DONE_PARTIAL;result.volume=(double)(p.volume/2)/100000;
      result.price=(double)p.price/100000;result.deal=1;return true;
   }
   // Independent durable history is written inside the simulated broker operation,
   // before its reply. A crash here is reconciled without submitting another request.
   if(!TrdSimulationEvidence(payload,hash,p)) return TrdStop("BROKER_LEDGER_FAILED");
   result.deal=p.action=="MODIFY_STOPS"?0:p.action=="CLOSE"?(ulong)(10000000000000000+trd_ledger_count):(ulong)trd_ledger_count;
   result.volume=p.action=="MODIFY_STOPS"?0:p.request.volume;result.price=p.action=="MODIFY_STOPS"?0:p.request.price;
   if(LocalBrokerScenario=="placed_with_evidence") result.retcode=TRADE_RETCODE_PLACED;
   if(LocalBrokerScenario=="timeout_with_evidence") result.retcode=TRADE_RETCODE_TIMEOUT;
   return true;
}
#endif
