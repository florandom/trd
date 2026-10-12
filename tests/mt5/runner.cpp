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
 <<",\"realized_pnl\":"<<TrdQuote(TrdMoney(trd_pnl))<<"}"<<std::endl;
}
int main(int argc,char **argv) {
 if(argc>=2&&string(argv[1])=="run") {
  if(argc!=7) return 2;
  LocalConfig=argv[2];host_root=argv[3];LocalCrashPoint=argv[4];ActivateLocalSimulation=string(argv[5])=="1";
  host_tester=string(argv[6])=="1";
  Stats(OnInit());string line;while(std::getline(std::cin,line)) { if(line=="STOP") break;if(line!="TICK") return 3;OnTimer();Stats(); }
  OnDeinit(0);return 0;
 }
 string line;while(std::getline(std::cin,line)) {
  if(line.rfind("JSON ",0)==0) { TrdJson doc;std::cout<<"{\"answer\":\""<<(doc.Parse(TrdHexAscii(line.substr(5)))?"VALID":"INVALID")<<"\"}"<<std::endl;continue; }
  TrdJson d;if(!d.Parse(line)) { std::cout<<"{}"<<std::endl;continue; }
  string op=d.Get("op"),answer="";
  if(op=="sha") answer=TrdSha256(d.Get("hex"));
  if(op=="hmac") answer=TrdHmac(d.Get("key"),d.Get("hex"));
  if(op=="json") { TrdJson doc;answer=doc.Parse(TrdHexAscii(d.Get("hex")))?"VALID":"INVALID"; }
  if(op=="decimal") { long n;answer=TrdDecimal(d.Get("value"),n)?IntegerToString(n):"INVALID"; }
  if(op=="base64") answer=TrdBase64(d.Get("value"));
  if(op=="frame") answer=TrdFrame(d.Get("environment"),d.Get("bridge"),d.Get("instance"),d.Get("key"),d.Get("journal"),d.Get("sequence"),d.Get("issued"),d.Get("expires"),d.Get("path"),0,"REQUEST",d.Get("hex"));
  std::cout<<"{\"answer\":"<<TrdQuote(answer==""?"":op=="frame"?TrdAsciiHex(answer):answer)<<"}"<<std::endl;
 }
 return 0;
}
