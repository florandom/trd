// Broker request adapter. No native terminal API or broker submission lives here.
// All economics remain fixed-point until the final MqlTradeRequest boundary.
#ifndef TRD_BROKER_MQH
#define TRD_BROKER_MQH
#include "TrdCore.mqh"

struct TrdBrokerContext
{
   string server,login,currency,position_mode,symbol;
   bool connected,trade_allowed,history_complete,portfolio_complete,attached_stops,fok,owned;
   long observed_at,bid,ask,point,tick,volume_min,volume_step,volume_max,stops,freeze;
   long ticket,identifier,magic,volume,entry,sl,tp,revision;
   string opening,side;
};
struct TrdBrokerPlan
{
   MqlTradeRequest request;
   long volume,price,sl,tp,deviation;
   string action,command_id,position_identifier;
};

bool TrdBrokerExternalCode(const string value)
{
   long code;bool negative=StringSubstr(value,0,1)=="-";
   if(!TrdUnsigned(negative?StringSubstr(value,1):value,code)) return false;
   return negative?(code>0&&code<=2147483648):code<=2147483647;
}

bool TrdBuildBrokerRequest(const string payload,const TrdBrokerContext &b,TrdBrokerPlan &p,string &reason)
{
   reason="BROKER_CONTEXT_UNSUPPORTED";
   TrdJson c;
   if(!c.Parse(payload)) return false;
   // Only this laboratory profile has evidence. No demo/live or symbol guessing.
   if(b.server!="TRD-PAPER-SIMULATOR"||b.login!="1"||b.currency!="USD"||b.position_mode!="hedging"||
      b.symbol!="EURUSD.paper"||c.Get("symbol")!=b.symbol||!b.connected||!b.trade_allowed||
      !b.history_complete||!b.portfolio_complete||!b.attached_stops||!b.fok||
      b.point!=1||b.tick!=1||b.volume_min!=1000||b.volume_step!=1000||b.volume_max!=100000||
      b.stops!=10||b.freeze!=5||b.observed_at>(long)TimeGMT()||(long)TimeGMT()-b.observed_at>2||
      b.bid<50000||b.ask>200000||b.bid>=b.ask) return false;
   int account=c.Field("account");
   if(c.Get("broker_server",account)!=b.server||c.Get("login",account)!=b.login||c.Get("mode",account)!="paper") return false;
   p.action=c.Get("action");p.command_id=c.Get("command_id");p.position_identifier=c.Get("position_identifier");
   string side=c.Get("side");
   reason="BROKER_REQUEST_INVALID";
   long low,high,spread,deviation;
   if(!TrdUuidValid(p.command_id)||(side!="BUY"&&side!="SELL")||
      (p.action!=""&&p.action!="CLOSE"&&p.action!="MODIFY_STOPS")||
      !TrdDecimal(c.Get("volume"),p.volume)||p.volume<b.volume_min||p.volume>b.volume_max||p.volume%b.volume_step!=0||
      !TrdDecimal(c.Get("stop_loss"),p.sl)||p.sl<=0||!TrdDecimal(c.Get("take_profit"),p.tp)||p.tp<=0||
      !TrdDecimal(c.Get("price_band_low"),low)||!TrdDecimal(c.Get("price_band_high"),high)||
      !TrdDecimal(c.Get("max_spread_points"),spread)||!TrdDecimal(c.Get("max_deviation_points"),deviation)) return false;
   if(spread>3000000) spread=3000000;if(deviation>2000000) deviation=2000000;
   p.deviation=deviation/100000; // Round down; never enlarge an approved deviation.
   p.price=p.action==""?(side=="BUY"?b.ask:b.bid):(side=="BUY"?b.bid:b.ask);
   if(low>high||p.price<low||p.price>high||high-low>2*p.deviation||(b.ask-b.bid)*100000>spread||
      TrdExpiry(c.Get("expires_at"))<=(long)TimeGMT()) return false;
   if(p.action!="CLOSE")
   {
      long loss=side=="BUY"?b.bid-p.sl:p.sl-b.ask,profit=side=="BUY"?p.tp-b.ask:b.bid-p.tp;
      if(loss<b.stops||profit<b.stops||loss<=b.freeze||profit<=b.freeze) return false;
   }
   if(p.action=="")
   {
      long risk;
      if(!TrdDecimal(c.Get("max_risk"),risk)||((side=="BUY"?p.price-p.sl:p.sl-p.price)+5)*p.volume+7*p.volume>risk) return false;
   }
   else
   {
      reason="BROKER_POSITION_CHANGED";
      long identifier,entry,entry_value,sl,tp,revision;
      if(!TrdUnsigned(p.position_identifier,identifier)||identifier<1||identifier!=b.identifier||b.ticket<1||
         !b.owned||b.magic!=20261012||b.volume!=p.volume||b.side!=side||b.opening!=c.Get("opening_command_id")||
         !TrdUnsigned(c.Get("position_revision"),revision)||revision!=b.revision||
         !TrdDecimal(c.Get("entry_price"),entry)||entry!=b.entry||
         !TrdScaledDecimal(c.Get("entry_value"),entry_value,10)||entry_value!=entry*p.volume||
         !TrdDecimal(c.Get("previous_stop_loss"),sl)||sl!=b.sl||
         !TrdDecimal(c.Get("previous_take_profit"),tp)||tp!=b.tp||
         (p.action=="CLOSE"?(p.sl!=sl||p.tp!=tp):(side=="BUY"?p.sl<sl:p.sl>sl))) return false;
   }
   MqlTradeRequest request={};
   request.symbol=b.symbol;request.magic=20261012;
   request.comment="trd:"+StringSubstr(TrdHash(p.command_id),0,24); // Hint, never ownership evidence.
   request.type_filling=ORDER_FILLING_FOK;request.type_time=ORDER_TIME_GTC;
   if(p.action=="MODIFY_STOPS")
   {
      request.action=TRADE_ACTION_SLTP;request.position=(ulong)b.ticket;
      request.sl=(double)p.sl/100000;request.tp=(double)p.tp/100000;
   }
   else
   {
      request.action=TRADE_ACTION_DEAL;request.volume=(double)p.volume/100000;
      request.price=(double)p.price/100000;request.deviation=(ulong)p.deviation;
      bool buy=p.action=="CLOSE"?side=="SELL":side=="BUY";
      request.type=buy?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
      if(p.action=="CLOSE") request.position=(ulong)b.ticket;
      else { request.sl=(double)p.sl/100000;request.tp=(double)p.tp/100000; }
   }
   p.request=request;reason="";return true;
}

// OrderSend's bool, a ticket, and DONE are not economic evidence. Only independent
// deal/position reconciliation may complete an executor command.
string TrdBrokerDisposition(const bool api_ok,const uint retcode)
{
   if(!api_ok) return "UNKNOWN";
   if(retcode==TRADE_RETCODE_DONE_PARTIAL) return "PARTIAL_UNSUPPORTED";
   if(retcode==TRADE_RETCODE_PLACED||retcode==TRADE_RETCODE_DONE) return "AWAIT_EVIDENCE";
   // Even an explicit post-send rejection retains the intent under the current
   // bridge contract. Releasing it requires a separately accepted reconciliation.
   return "UNKNOWN";
}

string TrdBrokerRequestJson(const TrdBrokerPlan &p)
{
   return "{\"action\":"+TrdQuote(p.action=="MODIFY_STOPS"?"SLTP":"DEAL")+
      ",\"symbol\":"+TrdQuote(p.request.symbol)+",\"magic\":\"20261012\",\"comment\":"+TrdQuote(p.request.comment)+
      ",\"position_ticket\":"+TrdQuote(IntegerToString((long)p.request.position))+
      ",\"position_identifier\":"+TrdQuote(p.position_identifier)+
      ",\"side\":"+TrdQuote(p.action=="MODIFY_STOPS"?"":p.request.type==ORDER_TYPE_BUY?"BUY":"SELL")+
      ",\"volume\":"+TrdQuote(TrdMoney(p.action=="MODIFY_STOPS"?0:p.volume))+
      ",\"price\":"+TrdQuote(TrdMoney(p.action=="MODIFY_STOPS"?0:p.price))+
      ",\"stop_loss\":"+TrdQuote(TrdMoney(p.action=="CLOSE"?0:p.sl))+
      ",\"take_profit\":"+TrdQuote(TrdMoney(p.action=="CLOSE"?0:p.tp))+
      ",\"deviation\":"+TrdQuote(IntegerToString(p.action=="MODIFY_STOPS"?0:p.deviation))+
      ",\"filling\":\"FOK\"}";
}
#endif
