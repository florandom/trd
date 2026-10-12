int WebRequest(const string &,const string &url,const string &headers,int,const std::vector<char> &data,std::vector<char> &result,string &response_headers) {
 std::cout<<"RPC\t"<<url<<"\t"<<TrdAsciiHex(headers)<<"\t"<<TrdAsciiHex(string(data.begin(),data.end()))<<std::endl;
 string line;if(!std::getline(std::cin,line)) return -1;
 auto first=line.find('\t'),last=line.find('\t',first+1);if(first==string::npos||last==string::npos) return -1;
 int status=std::stoi(line.substr(0,first));response_headers=TrdHexAscii(line.substr(first+1,last-first-1));
 string hex=line.substr(last+1);if(!TrdHex(hex)) return -1;
 for(int i=0;i<StringLen(hex)/2;i++) result.push_back(static_cast<char>(TrdByte(hex,i)));
 return status;
}
void Stats(int initialized=-1) {
 int active=0,unknown=0;for(int i=0;i<trd_position_count;i++) if(!trd_positions[i].closed) active++;
 for(int i=0;i<trd_command_count;i++) if(trd_commands[i].state=="UNKNOWN") unknown++;
 std::cout<<"{\"initialized\":"<<initialized<<",\"status\":"<<TrdQuote(trd_last_status)<<",\"fault\":"<<TrdQuote(trd_fault)
 <<",\"sequence\":"<<trd_sequence<<",\"operations\":"<<trd_ledger_count<<",\"positions\":"<<active<<",\"unknown\":"<<unknown
 <<",\"realized_pnl\":"<<TrdQuote(TrdMoney(trd_pnl))
 <<",\"broker_checks\":"<<trd_broker_checks<<",\"broker_replies\":"<<trd_broker_replies
 <<",\"broker_disposition\":"<<TrdQuote(trd_broker_disposition)
 <<",\"broker_request\":"<<(trd_broker_request.empty()?"null":trd_broker_request)<<"}"<<std::endl;
}
int main(int argc,char **argv) {
 if(argc>=2&&string(argv[1])=="run") {
  if(argc!=8) return 2;
  LocalConfig=argv[2];host_root=argv[3];LocalCrashPoint=argv[4];ActivateLocalSimulation=string(argv[5])=="1";
  host_tester=string(argv[6])=="1";
  LocalBrokerScenario=argv[7];
  Stats(OnInit());string line;while(std::getline(std::cin,line)) { if(line=="STOP") break;if(line!="TICK") return 3;OnTimer();Stats(); }
  OnDeinit(0);return 0;
 }
 string line;while(std::getline(std::cin,line)) {
  if(line.rfind("JSON ",0)==0) { TrdJson doc;std::cout<<"{\"answer\":\""<<(doc.Parse(TrdHexAscii(line.substr(5)))?"VALID":"INVALID")<<"\"}"<<std::endl;continue; }
  TrdJson d;if(!d.Parse(line)) { std::cout<<"{}"<<std::endl;continue; }
  string op=d.Get("op"),answer="";
  if(op=="broker_request") {
   trd_bid=109990;trd_ask=110000;
   TrdBrokerContext b=TrdSimulationContext("");
   auto number=[&](const string &key,long &value) { if(d.Field(key)>=0&&!TrdUnsigned(d.Get(key),value)) value=-1; };
   number("ticket",b.ticket);number("identifier",b.identifier);number("magic",b.magic);number("volume",b.volume);
   number("entry",b.entry);number("sl",b.sl);number("tp",b.tp);number("revision",b.revision);
   number("point",b.point);number("tick",b.tick);number("volume_step",b.volume_step);number("volume_max",b.volume_max);
   number("bid",b.bid);number("ask",b.ask);number("stops",b.stops);number("freeze",b.freeze);
   if(d.Field("server")>=0) b.server=d.Get("server");if(d.Field("login")>=0) b.login=d.Get("login");
   if(d.Field("currency")>=0) b.currency=d.Get("currency");if(d.Field("position_mode")>=0) b.position_mode=d.Get("position_mode");
   if(d.Field("symbol")>=0) b.symbol=d.Get("symbol");if(d.Field("opening")>=0) b.opening=d.Get("opening");
   if(d.Field("side")>=0) b.side=d.Get("side");
   if(d.Field("connected")>=0) b.connected=d.Get("connected")=="true";
   if(d.Field("trade_allowed")>=0) b.trade_allowed=d.Get("trade_allowed")=="true";
   if(d.Field("owned")>=0) b.owned=d.Get("owned")=="true";
   if(d.Field("fok")>=0) b.fok=d.Get("fok")=="true";
   if(d.Field("attached_stops")>=0) b.attached_stops=d.Get("attached_stops")=="true";
   TrdBrokerPlan p;string reason;
   if(!TrdBuildBrokerRequest(TrdHexAscii(d.Get("hex")),b,p,reason)) {
    std::cout<<"{\"answer\":"<<TrdQuote(reason)<<"}"<<std::endl;continue;
   }
   auto &r=p.request;
   std::cout<<"{\"answer\":"<<TrdQuote(TrdBrokerRequestJson(p))<<",\"native_request\":{\"action\":"<<r.action
   <<",\"type\":"<<r.type<<",\"filling\":"<<r.type_filling<<",\"volume\":"<<r.volume<<",\"price\":"<<r.price
   <<",\"sl\":"<<r.sl<<",\"tp\":"<<r.tp<<",\"position\":"<<TrdQuote(IntegerToString((long)r.position))<<"}}"<<std::endl;continue;
  }
  if(op=="sha") answer=TrdSha256(d.Get("hex"));
  if(op=="hmac") answer=TrdHmac(d.Get("key"),d.Get("hex"));
  if(op=="json") { TrdJson doc;answer=doc.Parse(TrdHexAscii(d.Get("hex")))?"VALID":"INVALID"; }
  if(op=="decimal") { long n;answer=TrdDecimal(d.Get("value"),n)?IntegerToString(n):"INVALID"; }
  if(op=="base64") answer=TrdBase64(d.Get("value"));
  if(op=="frame") answer=TrdFrame(d.Get("environment"),d.Get("bridge"),d.Get("instance"),d.Get("key"),d.Get("journal"),d.Get("sequence"),d.Get("issued"),d.Get("expires"),d.Get("path"),0,"REQUEST",d.Get("hex"));
  if(op=="disposition") {
   long code;if(TrdUnsigned(d.Get("retcode"),code)&&code<=4294967295) answer=TrdBrokerDisposition(d.Get("api_ok")=="true",(uint)code);
  }
  std::cout<<"{\"answer\":"<<TrdQuote(answer==""?"":op=="frame"?TrdAsciiHex(answer):answer)<<"}"<<std::endl;
 }
 return 0;
}
